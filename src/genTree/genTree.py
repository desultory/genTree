from os import chroot
from pathlib import Path
from shutil import rmtree
from subprocess import run
from tarfile import ReadError, TarFile

from zenlib.logging import loggify
from zenlib.util import colorize

from .filters import WhiteoutError
from .gen_tree_config import GenTreeConfig
from .types import MountMixins, OCIMixins


def get_world_set(config):
    """returns a set containing world entries under the build root of the supplied config"""
    try:
        with open(config.overlay_root / "var/lib/portage/world") as world:
            return set(world.read().splitlines())
    except FileNotFoundError:
        return set()


def preserve_world(func):
    """Preserves the world file of the config before running the function"""

    def wrapper(self, config, *args, **kwargs):
        world = get_world_set(config)
        ret = func(self, config, *args, **kwargs)
        new_world = get_world_set(config)
        for entry in world:
            if entry not in new_world:
                config.logger.info(f"[{colorize(config.name, "blue")}] Adding {colorize(entry, "green")} to world file")
                with open(config.overlay_root / "var/lib/portage/world", "a") as world:
                    world.write(entry + "\n")
        return ret

    return wrapper


@loggify
class GenTree(MountMixins, OCIMixins):
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    def prepare_build(self, config):
        """Prepares the build environment for the passed config"""
        if config.clean_build:
            config.logger.warning(
                " -.- [%s] Cleaning root: %s", colorize(config.name, "blue"), colorize(config.overlay_root, "red")
            )
            for root in ["overlay_root", "lower_root", "work_root", "upper_root"]:
                root_dir = getattr(config, root)
                if not root_dir.exists():
                    continue
                if root_dir.is_mount():
                    config.logger.warning(
                        "[%s] Unmounting root: %s",
                        colorize(config.name, "blue"),
                        colorize(root_dir, "yellow"),
                    )
                    run(["umount", root_dir], check=True)
                config.logger.debug("Cleaning root: %s", root_dir)
                rmtree(root_dir)

        config.check_dir(["overlay_root", "lower_root", "work_root", "upper_root"])

    def build_bases(self, config):
        """Builds the bases for the current config"""
        if bases := config.bases:
            for base in bases:
                base.logger.info(
                    " +.+ [%s] Building base: %s",
                    colorize(config.file_display_name, "cyan"),
                    colorize(base.name, "blue", bold=True),
                )
                self.build(config=base)

    @preserve_world
    def deploy_base(self, config, base, dest, deployed_bases=None, pretend=False):
        """Deploys bases over the config lower root. Recursively deploys bases of the base."""
        deployed_bases = [] if deployed_bases is None else deployed_bases
        if base.layer_archive in deployed_bases:
            return base.logger.debug("Skipping base as it has already been deployed: %s", base.layer_archive)

        try:
            with TarFile.open(base.layer_archive, "r") as tar:
                tar.extractall(dest, filter=config.whiteout_filter)
        except ReadError as e:
            raise RuntimeError(f"[{base.name}] Failed to extract base layer: {base.layer_archive}") from e

        # Apply opaques and whiteouts to adhere to the OCI spec, from OCIMixins
        self.apply_opaques(dest, config.opaques)
        self.apply_whiteouts(dest, config.whiteouts)

    def deploy_bases(self, config, dest=None, deployed_bases=None, pretend=False):
        """Deploys the bases to the lower dir for the current config.
        Mounts an overlayfs on the build root."""
        dest = dest or config.lower_root
        bases = getattr(config, "bases")
        if not bases:
            return

        deployed_bases = [] if deployed_bases is None else deployed_bases
        for base in bases:
            self.logger.debug("[%s] Handling base: %s", config.name, base.name)
            self.deploy_bases(config=base, dest=dest, deployed_bases=deployed_bases, pretend=pretend)
            self.deploy_base(config=config, base=base, dest=dest, deployed_bases=deployed_bases, pretend=pretend)
            deployed_bases.append(base.layer_archive)
        return deployed_bases

    def run_emerge(self, args, config: GenTreeConfig = None):
        """Runs the emerge command with the passed args"""
        self.logger.info(
            "[%s] emerge %s", colorize(config.name, "green", bright=True, bold=True), " ".join(map(str, args))
        )
        ret = run(["emerge", *args], capture_output=True)
        if ret.returncode:
            self.logger.error("Emerge info:\n" + run(["emerge", "--info"], capture_output=True).stdout.decode())
            raise RuntimeError(f"Failed to run: {args}\n{ret.stdout.decode()}\n{ret.stderr.decode()}")

        return ret

    def perform_emerge(self, config):
        """Performs the emerge command for the current config"""
        if not getattr(config, "packages", None):
            config.logger.debug("[%s] No packages to build", colorize(config.config_file, "blue", bold=True))
            return
        self.run_emerge(config.emerge_flags, config=config)

        if config.depclean:
            self.run_emerge(["--root", config.overlay_root, "--depclean", "--with-bdeps=n"], config=config)

    def perform_unmerge(self, config):
        """unmerges the packages in the unmerge list"""
        if not getattr(config, "unmerge", None):
            return

        packages = config.unmerge or []
        config.logger.info(
            "[%s] Unmerging packages: %s", colorize(config.name, "blue"), colorize(", ".join(packages), "red")
        )
        self.run_emerge(["--root", config.overlay_root, "--unmerge", *packages], config=config)

    def build(self, config):
        """Builds all bases and branches under the current config
        Builds/installs packages in the config build root
        Unmerges packages in the config unmerge list
        Packs the build tree into the config layer archive if no_pack is False"""
        self.build_bases(config=config)
        if config.layer_archive.exists() and not config.rebuild:
            return config.logger.warning(
                " ... [%s] Skipping build, layer archive exists: %s",
                colorize(config.name, "blue"),
                colorize(config.layer_archive, "cyan"),
            )

        self.prepare_build(config=config)
        self.deploy_bases(config=config)
        self.mount_root_overlay(config=config)
        self.mount_config_overlay(config=config)
        config.set_portage_profile()
        config.set_portage_env()
        self.perform_emerge(config=config)
        self.perform_unmerge(config=config)
        config.cleaner.clean(config.overlay_root)
        self.pack(config=config)

    def pack(self, config):
        """Packs the upper dir of the layer into {config.layer_archive}.
        The layer archive will be {config.seed}-{config.name} unless  `output_file` is set."""
        config.logger.info(
            "[%s] Packing tree: %s",
            colorize(config.name, "blue", bold=True),
            colorize(config.layer_archive, "magenta"),
        )

        with TarFile.open(config.layer_archive, "w") as tar:
            for file in config.upper_root.rglob("*"):
                archive_path = file.relative_to(config.upper_root)
                config.logger.log(5, f"[{config.upper_root}] Adding file: {archive_path}")
                try:
                    tar.add(
                        file,
                        arcname=archive_path,
                        filter=config.tar_filter,
                        recursive=False,
                    )
                except WhiteoutError as e:
                    config.logger.log(5, e)
                    tar.addfile(e.whiteout)

        self.logger.info(
            "[%s] Created archive: %s (%s)",
            colorize(config.name, "blue", bold=True),
            colorize(config.layer_archive, "green", bold=True),
            colorize("{:.2f} MB".format(config.layer_archive.stat().st_size / 2**20), "green", bright=True),
        )

    def pack_all(self, config):
        """Packs all layers in the config into the output file"""
        config.logger.info(
            "[%s] Packing all layers into: %s",
            colorize(config.name, "blue", bold=True),
            colorize(config.output_archive, "green", bright=True),
        )

        def re_add(tar, file, base):
            if file.isreg():
                tar.addfile(file, base.extractfile(file))
            else:
                tar.addfile(file)

        bases = self.deploy_bases(config=config, pretend=True)
        bases.append(config.layer_archive)
        self.logger.info(
            "[%s] Packing bases: %s", colorize(config.name, "blue"), colorize(", ".join(map(str, bases)), "cyan")
        )
        pre_tar = config.output_archive.with_suffix(".pre.tar")
        with TarFile.open(pre_tar, "w") as tar:
            tar_filter = self.config.whiteout_filter
            for base in bases:
                self.logger.debug("[%s] Adding base archive: %s", config.name, base)
                with TarFile.open(base, "r") as base_tar:
                    for file in base_tar:
                        if f := tar_filter(file):
                            self.logger.log(5, f"[{base}] Adding file: {f.name}")
                            re_add(tar, f, base_tar)
                        else:  # Skip filtered files
                            self.logger.log(5, "[%s] Skipping file: %s", config.name, file.name)
        if not config.whiteouts:
            self.logger.debug("[%s] No whiteouts found, renaming pre tar to final tar", config.name)
            pre_tar.rename(config.output_archive)
        else:
            tar_filter = self.config.tar_filter
            self.logger.debug("[%s] Applying whiteouts:\n%s", config.name, config.whiteouts)
            with TarFile.open(config.output_archive, "w") as tar:
                with TarFile.open(pre_tar, "r") as pre:
                    for file in pre:
                        if file.name in config.whiteouts:
                            self.logger.debug("[%s] Skipping whiteout: %s", config.name, file.name)
                            continue
                        re_add(tar, file, pre)
            pre_tar.unlink()

        if config.refilter:
            size = colorize("{:.2f} MB".format(config.output_archive.stat().st_size / 2**20), "green")
            self.logger.info(
                "[%s] Refiltering archive: %s (%s)",
                colorize(config.name, "blue"),
                colorize(config.output_archive, "yellow"),
                size,
            )
            config.output_archive.rename(pre_tar)  # Reuse the name
            tar_filter = self.config.tar_filter
            with TarFile.open(config.output_archive, "w") as tar:
                with TarFile.open(pre_tar, "r") as pre:
                    for file in pre:
                        if f := tar_filter(file):
                            self.logger.debug("[%s] Adding file: %s", config.name, f.name)
                            re_add(tar, f, pre)
                        else:
                            self.logger.debug("[%s] Skipping file: %s", config.name, file.name)
            pre_tar.unlink()

        self.logger.info(
            "[%s] Created final archive: %s (%s)",
            colorize(config.name, "blue", bold=True),
            colorize(config.output_archive, "green", bold=True),
            colorize("{:.2f} MB".format(config.output_archive.stat().st_size / 2**20), "green", bright=True),
        )

    def clean_seed_overlay(self):
        """Cleans the seed upper and work dirs"""
        for root in ["upper", "work"]:
            seed_root = Path(getattr(self.config, f"{root}_seed_root"))
            if seed_root.exists():
                self.logger.info(" --- Cleaning seed root: %s", colorize(seed_root, "red"))
                rmtree(seed_root)
            else:
                self.logger.debug("Seed root does not exist: %s", seed_root)

    def init_namespace(self):
        """Initializes the namespace for the current config"""
        self.logger.info("[%s] Initializing namespace", colorize(self.config.name, "blue"))
        if self.config.clean_seed:
            self.clean_seed_overlay()
        self.mount_seed_overlay()
        self.mount_system_dirs()
        self.bind_mount(self.config.system_repos, self.config.sysroot / "var/db/repos")
        self.bind_mount("/etc/resolv.conf", self.config.sysroot / "etc/resolv.conf", file=True)
        self.bind_mount(self.config.pkgdir, self.config.sysroot / "var/cache/binpkgs", readonly=False)
        self.bind_mount(self.config.build_dir, self.config.build_mount, recursive=True, readonly=False)
        self.bind_mount(self.config.config_dir, self.config.config_mount, recursive=True, readonly=False)
        self.logger.info(" -/~ Chrooting into: %s", colorize(self.config.sysroot, "red"))
        chroot(self.config.sysroot)

    def build_tree(self):
        """Builds the tree in a namespaced chroot environment.
        Packs the resulting tree into {self.output_file} or {self.config.layer_archive}."""
        self.init_namespace()
        self.logger.info(" +++ Building tree for: %s", colorize(self.config.name, "blue", bold=True, bright=True))
        self.build(config=self.config)
        self.pack_all(config=self.config)  # Pack the entire tree
