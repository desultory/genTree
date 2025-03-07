from os import chdir, chroot
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run
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
    def __init__(self, config_file=None, *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

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

        if not Path(dest).exists():
            base.logger.debug("Creating parent directories for: %s", dest)
            Path(dest).mkdir(parents=True)

        try:
            with TarFile.open(base.layer_archive, "r") as tar:
                tar.extractall(dest, filter=config.whiteout_filter)
            base.logger.debug("[%s] Extracted base: %s", config.name, base.layer_archive)
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
        if not bases:  # Make sure the lower root is created since there are no bases to deploy
            config.check_dir("lower_root")
            return []

        deployed_bases = [] if deployed_bases is None else deployed_bases
        for base in bases:
            self.logger.debug("[%s] Handling base: %s", config.name, base.name)
            self.deploy_bases(config=base, dest=dest, deployed_bases=deployed_bases, pretend=pretend)
            self.deploy_base(config=config, base=base, dest=dest, deployed_bases=deployed_bases, pretend=pretend)
            deployed_bases.append(base.layer_archive)
        return deployed_bases

    def run_emerge(self, args, config: GenTreeConfig = None):
        """Runs the emerge command with the passed args"""
        config = config or self.config
        emerge_cmd = config.emerge_cmd
        config.set_portage_profile()  # Ensure the profile is set
        config.set_portage_env()  # Ensure the env is set

        self.logger.info(
            " [E] [%s] %s %s",
            colorize(config.name, "green", bright=True, bold=True),
            colorize(emerge_cmd, "magenta", bright=True, bold=True) if emerge_cmd != "emerge" else "emerge",
            " ".join(map(str, args)),
        )
        # Open the emerge log, get the current last line so it can be seeked past in the event of build failures
        emerge_log = Path("/var/log/emerge.log")
        emerge_log.touch()
        log_end = emerge_log.stat().st_size
        ret = run([emerge_cmd, *args])

        if ret.returncode:
            self.logger.error("Emerge info:\n" + run(["emerge", "--info"], capture_output=True).stdout.decode())
            with open(emerge_log, "r") as log:
                log.seek(log_end)
                self.logger.error("Emerge log:\n" + log.read())
            raise RuntimeError(f"Failed to run: emerge {args}")

        return ret

    def perform_emerge(self, config):
        """Performs the emerge command for the current config"""
        if not getattr(config, "packages", None):
            return config.logger.debug("[%s] No packages to build", colorize(config.config_file, "blue", bold=True))

        packages = config.packages or []
        config.logger.info(
            " [E] [%s] Emerging packages: %s", colorize(config.name, "blue"), colorize(", ".join(packages), "green")
        )
        self.run_emerge(config.emerge_flags, config=config)

        if config.depclean:
            self.run_emerge(["--root", config.overlay_root, "--depclean", "--with-bdeps=n"], config=config)

    def perform_unmerge(self, config):
        """unmerges the packages in the unmerge list"""
        if not getattr(config, "unmerge", None):
            return

        packages = config.unmerge or []
        config.logger.info(
            " [U] [%s] Unmerging packages: %s", colorize(config.name, "blue"), colorize(", ".join(packages), "red")
        )
        self.run_emerge(["--root", config.overlay_root, "--unmerge", *packages], config=config)

    def build(self, config):
        """Builds all bases and branches under the current config
        Builds/installs packages in the config build root
        Unmerges packages in the config unmerge list
        Packs the build tree into config.layer_archive."""
        self.build_bases(config=config)
        if config.layer_archive.exists() and not config.rebuild:
            return config.logger.warning(
                " ... [%s] Skipping build, layer archive exists: %s",
                colorize(config.name, "blue"),
                colorize(config.layer_archive, "cyan"),
            )

        self.deploy_bases(config=config)
        self.overlay_mount(mountpoint=config.overlay_root, lower=config.lower_root, upper=config.upper_root)
        self.mount_config_overlay(config=config)
        self.perform_emerge(config=config)
        self.perform_unmerge(config=config)
        config.cleaner.clean(config.overlay_root)
        self.pack(config=config)

    def pack(self, config):
        """Packs the upper dir of the layer into config.layer_archive.
        The file is named config.buildname which is {config.name}-{config.buildname}"""
        config.logger.info(
            " >:- [%s] Packing tree: %s",
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
        """Packs all layers in the config into the output file
        If refilter is True, refilters the archive after applying whiteouts"""
        config.logger.info(
            " V:V [%s] Packing all layers into: %s",
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
            " #%%- [%s] Packing bases: %s", colorize(config.name, "blue"), colorize(", ".join(map(str, bases)), "cyan")
        )
        pre_tar = config.output_archive.with_suffix(".pre.tar")
        with TarFile.open(pre_tar, "w") as tar:
            tar_filter = self.config.whiteout_filter
            for base in bases:
                self.logger.debug("[%s] Adding base archive: %s", config.name, base)
                with TarFile.open(base, "r") as base_tar:
                    for file in base_tar:
                        # Don't add directories over existing symlinks
                        if file.isdir() and file.name in tar.getnames():
                            self.logger.debug("[%s] Skipping existing directory: %s", config.name, file.name)
                            continue
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
                        elif any(file.name.startswith(f"{whiteout}/") for whiteout in config.whiteouts):
                            self.logger.debug("[%s] Skipping prefixed whiteout: %s", config.name, file.name)
                            continue
                        re_add(tar, file, pre)
            pre_tar.unlink()

        if config.refilter:
            size = colorize("{:.2f} MB".format(config.output_archive.stat().st_size / 2**20), "green")
            self.logger.info(
                " ~%%> [%s] Refiltering archive: %s (%s)",
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

    def init_namespace(self):
        """Initializes the namespace for the current config
        If clean_seed is True, cleans the seed overlay upper and work dirs
        """
        self.logger.info("[%s] Initializing namespace", colorize(self.config.name, "blue"))

        self.mount_seed_overlay()  # Mount the seed overlay, if no_seed_overlay is False (default)
        self.mount_system_dirs()  # Mount system dirs, such as /sys, /proc, /dev
        self.mount_repos() # Mount system or user repos
        self.bind_mount("/etc/resolv.conf", self.config.sysroot / "etc/resolv.conf", file=True)
        self.bind_mount(self.config.pkgdir, self.config.pkgdir_mount, readonly=False)
        self.bind_mount(self.config.distfile_dir, self.config.sysroot / "var/cache/distfiles", readonly=False)
        self.bind_mount(self.config.build_dir, self.config.build_mount, recursive=True, readonly=False)
        self.bind_mount(self.config.config_dir, self.config.config_mount, recursive=True, readonly=False)
        self.logger.info(" -/~ Chrooting into: %s", colorize(self.config.sysroot, "red"))
        chroot(self.config.sysroot)
        chdir("/")

    def execute(self, args):
        """Runs a command in the namespace environment"""
        self.init_namespace()
        self.logger.info(" ### Running command: %s", colorize(args, "green"))
        run(args)

    def update_seed(self):
        """Updates the seed overlay"""
        self.config.clean_seed = True  # Clean the seed upper/work dirs
        self.config.no_seed_overlay = True  # Don't use an overlay, work on the seed
        self.init_namespace()
        self.logger.info(" >>> Updating seed: %s", colorize(self.config.seed_update_args, "green"))
        self.run_emerge(split(self.config.seed_update_args))
        self.run_emerge(["--depclean"])  # Depclean after world update

    def init_crossdev(self, chain):
        """Creates a crossdev toolchain given a chain tuple
        Emerge the crossdev package on a clean, updated seed
        """
        self.config.env["features"].remove("usersandbox")
        self.init_namespace()
        self.run_emerge(["--usepkg=y", "--noreplace", "crossdev", "eselect-repository"])
        try:
            cmd = run(["eselect", "repository", "enable", "crossdev"], check=True, capture_output=True)
            if "repository already enabled" in cmd.stdout.decode():
                self.logger.debug("Crossdev repository already enabled")
        except CalledProcessError as e:
            raise RuntimeError("Failed to enable crossdev repository: %s" % e.stderr.decode()) from e

        try:
            run(["crossdev", "--target", chain], check=True)
        except CalledProcessError as e:
            self.logger.error("Failed to run crossdev: %s", e.stderr.decode())
            raise RuntimeError("Failed to create crossdev toolchain") from e

    def stage_crossdev(self, chain):
        """ Stages the crossdev environment,
        Sets a profile and emerges base packages such as glibc.
        """
        self.init_namespace()
        def emerge_bases(config):
            if config.bases:
                for base in config.bases:
                    emerge_bases(base)
            config.crossdev_target = chain  # Force using crossdev
            config.emerge_bools["oneshot"] = True
            if not config.packages:
                return  # Don't do anyhting if packaegs aren't defined
            self.run_emerge(config.emerge_flags[2:], config=config)
        emerge_bases(self.config)


    def build_tree(self):
        """Builds the tree in a namespaced chroot environment.
        Packs the resulting tree into {self.config.output_file} or {self.config.output_archive}."""
        self.init_namespace()
        self.logger.info(" +++ Building tree for: %s", colorize(self.config.name, "blue", bold=True, bright=True))
        self.build(config=self.config)
        self.pack_all(config=self.config)  # Pack the entire tree

    def build_package(self, package):
        """Builds a single package based on the current config"""
        self.init_namespace()
        self.logger.info(" +++ Building package: %s", colorize(package, "green", bold=True))
        self.run_emerge(
            ["--oneshot", "--autounmask=y", "--autounmask-continue=y", "--usepkg=y", "--jobs=8", "--noreplace", package]
        )
