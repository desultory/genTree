from os import chroot
from shutil import rmtree
from subprocess import run
from tarfile import ReadError, TarFile

from zenlib.logging import loggify
from zenlib.util import colorize

from .gen_tree_config import GenTreeConfig
from .gen_tree_tar_filter import WhiteoutError
from .mount_mixins import MountMixins
from .oci_mixins import OCIMixins


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

    def build_bases(self, config):
        """Builds the bases for the current config"""
        if bases := config.bases:
            for base in bases:
                base.logger.info(
                    "[%s] Building base: %s",
                    colorize(config.file_display_name, "cyan"),
                    colorize(base.name, "blue", bold=True),
                )
                self.build(config=base)

    def prepare_build(self, config):
        """Prepares the build environment for the passed config"""
        if config.clean_build:
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
                config.logger.warning(
                    "[%s] Cleaning root: %s", colorize(config.name, "blue"), colorize(root_dir, "red")
                )
                rmtree(root_dir)

        config.check_dir(["overlay_root", "lower_root", "work_root", "upper_root"])

    @preserve_world
    def deploy_base(self, config, base, dest=None, deployed_bases=None):
        """Deploys bases over the config lower root. Recursively deploys bases of the base."""
        dest = dest or config.lower_root
        deployed_bases = deployed_bases or []
        for sub_base in base.bases:
            if sub_base.name in deployed_bases:
                self.logger.debug("Skipping base as it has already been deployed: %s", sub_base.name)
                continue
            self.deploy_base(config=config, base=sub_base, dest=dest, deployed_bases=deployed_bases)
            deployed_bases.append(sub_base.name)
        config.logger.info(
            "[%s] Unpacking base layer to build root: %s",
            colorize(base.name, "blue"),
            colorize(dest, "yellow"),
        )
        try:
            with TarFile.open(base.layer_archive, "r") as tar:
                tar.extractall(dest, filter=config.whiteout_filter)
        except ReadError as e:
            raise RuntimeError(f"[{config.name}] Failed to extract base layer: {base.layer_archive}") from e

        # Apply opaques and whiteouts to adhere to the OCI spec, from OCIMixins
        self.apply_opaques(dest, config.opaques)
        self.apply_whiteouts(dest, config.whiteouts)

    def activate_seed(self, config):
        """Mounts an overlayfs in a user namespace for the seed"""
        config.logger.info(
            "[%s] Activating seed: %s",
            colorize(config.name, "blue"),
            colorize(config.seed, "cyan"),
        )
        self.mount_seed(config)

    def deploy_bases(self, config, deployed_bases=None):
        """Deploys the bases to the lower dir for the current config.
        Mounts an overlayfs on the build root."""
        bases = getattr(config, "bases")
        if not bases:
            return
        # Add something so subsequent deploys don't init a new list
        deployed_bases = deployed_bases or [config.name]

        for base in bases:
            if base.name in deployed_bases:
                config.logger.debug("Skipping base as it has already been deployed: %s", base.name)
                continue
            self.deploy_base(config=config, base=base, deployed_bases=deployed_bases)
            deployed_bases.append(base.name)

    def run_emerge(self, args, config: GenTreeConfig = None):
        """Runs the emerge command with the passed args"""
        self.logger.info("Running emerge with args: " + " ".join(map(str, args)))
        ret = run(["emerge", *args], capture_output=True)
        if ret.returncode:
            self.logger.error("Emerge info:\n" + run(["emerge", "--info"], capture_output=True).stdout.decode())
            raise RuntimeError(f"Failed to run emerge with args: {args}\n{ret.stdout.decode()}\n{ret.stderr.decode()}")

        return ret

    def perform_emerge(self, config):
        """Performs the emerge command for the current config"""
        if not getattr(config, "packages", None):
            config.logger.debug("[%s] No packages to build", colorize(config.config_file, "blue", bold=True))
            return

        self.run_emerge(config.get_emerge_args(), config=config)

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

    def build(self, config, no_pack=False):
        """Builds all bases and branches under the current config
        Builds/installs packages in the config build root
        Unmerges packages in the config unmerge list
        Packs the build tree into the config layer archive if no_pack is False"""
        self.build_bases(config=config)
        if config.layer_archive.exists() and not config.rebuild:
            return config.logger.warning(
                "[%s] Skipping build, layer archive exists: %s",
                colorize(config.name, "blue"),
                colorize(config.layer_archive, "cyan"),
            )

        self.prepare_build(config=config)
        self.deploy_bases(config=config)
        self.mount_root_overlay(config=config)
        config.set_portage_profile()
        config.set_portage_env()
        self.perform_emerge(config=config)
        self.perform_unmerge(config=config)
        if not no_pack:
            self.pack(config=config)

        return True

    def pack(self, config, pack_all=False):
        """Packs the built tree into {config.layer_archive}.
        Unmounts the build root if it is a mount."""
        pack_root = config.overlay_root if not config.bases or pack_all else config.upper_root
        config.logger.info(
            "[%s] Packing tree to: %s",
            colorize(config.name, "blue", bold=True),
            colorize(config.layer_archive, "green", bold=True),
        )
        with TarFile.open(config.layer_archive, "w") as tar:
            for file in pack_root.rglob("*"):
                archive_path = file.relative_to(pack_root)
                config.logger.log(5, f"[{pack_root}] Adding file: {archive_path}")
                try:
                    tar.add(
                        file,
                        arcname=archive_path,
                        filter=config.tar_filter,
                        recursive=False,
                    )
                except WhiteoutError as e:
                    self.logger.debug("Whiteout detected: %s", e)
                    tar.addfile(e.whiteout)

        self.logger.info(
            "[%s] Created archive: %s",
            colorize(config.name, "blue", bold=True),
            colorize(config.layer_archive, "green", bold=True),
        )

    def init_namespace(self):
        """Initializes the namespace for the current config"""
        self.logger.info("[%s] Initializing namespace", colorize(self.config.name, "blue"))
        self.mount_seed_overlay()
        self.mount_system_dirs()
        self.bind_mount(self.config.system_repos, self.config.sysroot / "var/db/repos")
        self.bind_mount(
            self.config.pkgdir.expanduser().resolve(), self.config.sysroot / "var/cache/binpkgs", readonly=False
        )
        self.bind_mount("/etc/resolv.conf", self.config.sysroot / "etc/resolv.conf", file=True)
        self.bind_mount(
            self.config.build_dir.expanduser().resolve(), self.config.build_mount, recursive=True, readonly=False
        )
        self.logger.info("Chrooting into: %s", colorize(self.config.sysroot, "red"))
        chroot(self.config.sysroot)

    def build_tree(self):
        """Builds the tree.
        Packs the resulting tree into {self.output_file} or {self.config.layer_archive}."""
        self.init_namespace()
        self.logger.info("Building tree for: %s", colorize(self.config.name, "blue", bold=True, bright=True))
        if self.build(config=self.config, no_pack=True):  # If there is nothing to build, don't pack
            self.pack(config=self.config, pack_all=True)
