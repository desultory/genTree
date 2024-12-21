from pathlib import Path
from shutil import rmtree
from subprocess import run
from tarfile import ReadError, TarFile

from zenlib.logging import loggify

from .genTreeConfig import GenTreeConfig
from .genTreeTarFilter import GenTreeTarFilter


def get_world_set(config):
    """returns a set containing world entries under the root of the supplied config"""
    try:
        with open(config.root / "var/lib/portage/world") as world:
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
                config.logger.info(f"[{config.name}] Adding {entry} to world file")
                with open(config.root / "var/lib/portage/world", "a") as world:
                    world.write(entry + "\n")
        return ret

    return wrapper


@loggify
class GenTree:
    def __init__(self, config_file="config.toml", output_file="out.tar", *args, **kwargs):
        self.output_file = Path(output_file)
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    def build_bases(self, config):
        """Builds the bases for the current config"""
        if bases := config.bases:
            for base in bases:
                base.logger.info(f"[{config.config_file}] Building base: {base.name}")
                self.build(config=base)

    def prepare_build(self, config):
        """Prepares the build environment for the passed config"""
        if str(config.root) == "/":
            raise RuntimeError("Cannot build in root directory.")

        if config.clean_build:
            for root in ["root", "lower_root", "work_root", "upper_root"]:
                root_dir = getattr(config, root)
                if not root_dir.exists():
                    continue
                if root_dir.is_mount():
                    config.logger.warning(f"[{config.name}] Unmounting root: {root_dir}")
                    run(["umount", root_dir], check=True)
                config.logger.warning(f"[{config.name}] Cleaning root: {root_dir}")
                rmtree(root_dir, ignore_errors=True)

        config.check_dir("root")
        config.check_dir("config_root", create=False)

    @preserve_world
    def deploy_base(self, config, base, dest=None):
        """Deploys bases over the config root. Recursively deploys bases of the base."""
        dest = dest or config.lower_root
        config.logger.info(f"[{base.name}] Unpacking base layer to lower build root: {dest}")
        for sub_base in base.bases:
            self.deploy_base(config=config, base=sub_base, dest=dest)
        try:
            with TarFile.open(base.layer_archive, "r") as tar:
                tar.extractall(dest, filter=GenTreeTarFilter(logger=config.logger))
        except ReadError as e:
            raise RuntimeError(f"[{config.name}] Failed to extract base layer: {base.layer_archive}") from e

    def deploy_bases(self, config):
        """Deploys the bases to the lower dir for the current config.
        Mounts an overlayfs on the build root."""
        bases = getattr(config, "bases")
        if not bases:
            return
        config.check_dir("lower_root")
        for base in bases:
            self.deploy_base(config=config, base=base)
        config.check_dir("work_root")
        config.check_dir("upper_root")
        self.logger.info(f"[{config.name}] Mounting overlayfs on: {config.root}")
        run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"lowerdir={config.lower_root},upperdir={config.upper_root},workdir={config.work_root}",
                config.root,
            ],
            check=True,
        )

    def run_emerge(self, args):
        """Runs the emerge command with the passed args"""
        self.logger.info("Running emerge with args: " + " ".join(args))
        ret = run(["emerge", *args], capture_output=True)
        if ret.returncode:
            self.logger.error("Emerge info:\n" + run(["emerge", "--info"], capture_output=True).stdout.decode())
            raise RuntimeError(f"Failed to run emerge with args: {args}\n{ret.stdout.decode()}\n{ret.stderr.decode()}")

        return ret

    def perform_emerge(self, config):
        """Performs the emerge command for the current config"""
        if not getattr(config, "packages", None):
            config.logger.debug(f"[{config.config_file}] No packages to build")
            config.built = True
            return

        emerge_args = config.get_emerge_args()
        config.set_portage_env()
        self.run_emerge(emerge_args)

        if config.depclean:
            self.run_emerge(["--root", str(config.root), "--depclean", "--with-bdeps=n"])

    def perform_unmerge(self, config):
        """depcleans the packages in the unmerge list"""
        if not getattr(config, "unmerge", None):
            return

        for package in config.unmerge:
            self.logger.info(f"[{config.name}] Depcleaning package: {package}")
            self.run_emerge(["--root", str(config.root), "--depclean", package])

    def build(self, config):
        """Builds all bases and branches under the current config
        Then builds the packages in the config"""
        if config.layer_archive.exists() and not config.rebuild:
            return config.logger.warning(
                f"[{config.name}] Skipping build, layer archive exists: {config.layer_archive}"
            )

        self.build_bases(config=config)
        self.prepare_build(config=config)
        self.deploy_bases(config=config)
        self.perform_emerge(config=config)
        self.perform_unmerge(config=config)
        self.pack(config=config)

    def pack(self, config, pack_all=False, output_file=None):
        """Packs the built tree into {config.layer_archive}"""
        pack_root = config.root if not config.bases or pack_all else config.upper_root
        output_file = output_file or config.layer_archive
        config.logger.info(f"[{pack_root}] Packing tree to: {output_file}")
        with TarFile.open(output_file, "w") as tar:
            for file in pack_root.rglob("*"):
                archive_path = file.relative_to(pack_root)
                if archive_path in tar.getnames():
                    config.logger.warning(f"[{pack_root}] Skipping duplicate file: {archive_path}")
                    continue
                config.logger.debug(f"[{pack_root}] Adding file: {archive_path}")
                tar.add(
                    file,
                    arcname=archive_path,
                    filter=GenTreeTarFilter(logger=config.logger),
                    recursive=False,
                )

        self.logger.info("Created layer archive: %s", output_file)

    def build_tree(self):
        """Builds the tree"""
        self.logger.info(f"[{self.config.name}] Building tree at: {self.config.root}")
        self.build(config=self.config)
        self.pack(config=self.config, pack_all=True, output_file=self.output_file)
