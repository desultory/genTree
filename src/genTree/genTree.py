from shutil import rmtree
from subprocess import run
from tarfile import TarFile

from zenlib.logging import loggify

from .genTreeConfig import GenTreeConfig


def preserve_world(func):
    """Preserves the world file of the config before running the function"""
    def get_world_set(config):
        """returns a set containing world entries under the root of the supplied config"""
        with open(config.root / "var/lib/portage/world") as world:
            return set(world.read().splitlines())

    def wrapper(self, config, *args, **kwargs):
        try:
            world = get_world_set(config)
        except FileNotFoundError:
            world = set()
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
    def __init__(self, config_file="config.toml", *args, **kwargs):
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

        if config.root.exists() and config.clean_build:
            config.logger.warning(f"[{config.name}] Cleaning root: {config.root}")
            rmtree(config.root, ignore_errors=True)

        config.check_dir("root")
        config.check_dir("config_root", create=False)

    @preserve_world
    def deploy_base(self, config, base):
        """Deploys a base over the config root"""
        config.logger.info(f"[{base.name}] Unpacking base layer to build root: {config.root}")
        with TarFile.open(base.layer_archive, "r") as tar:
            tar.extractall(config.root)

    def deploy_bases(self, config):
        """Deploys the bases for the current config"""
        bases = getattr(config, "bases")
        if not bases:
            return
        for base in bases:
            self.deploy_base(config=config, base=base)

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

    def build(self, config):
        """Builds all bases and branches under the current config
        Then builds the packages in the config"""
        if config.layer_archive.exists() and not config.rebuild:
            return config.logger.warning(f"[{config.name}] Skipping build, layer archive exists")

        self.build_bases(config=config)
        self.prepare_build(config=config)
        self.deploy_bases(config=config)
        self.perform_emerge(config=config)
        self.pack(config=config)

    def pack(self, config):
        """Packs the built tree into {config.layer_archive}"""
        self.logger.info(f"[{config.root}] Packing tree to: {config.layer_archive}")
        with TarFile.open(config.layer_archive, "w") as tar:
            for file in config.root.rglob("*"):
                tar.add(file, arcname=file.relative_to(config.root))

    def build_tree(self):
        """Builds the tree"""
        self.logger.info(f"[{self.config.name}] Building tree at: {self.config.root}")
        self.build(config=self.config)
