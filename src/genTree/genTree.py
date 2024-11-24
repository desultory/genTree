from shutil import copytree, rmtree
from subprocess import run

from zenlib.logging import loggify

from .genTreeConfig import GenTreeConfig


@loggify
class GenTree:
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    def build_bases(self, config):
        """Builds the bases for the current config"""
        if bases := config.bases:
            for base in bases:
                self.logger.info(f"[{config.config_file}] Building base: {base.config_file}")
                self.build(config=base)

    def build_branches(self, config):
        """Builds the branches under the current branch"""
        if branches := config.branches:
            for branch in branches:
                self.logger.info(f"[{config.config_file}] Building branch: {branch.config_file}")
                self.build(config=branch)

    def prepare_build(self, config):
        """Prepares the build environment for the passed config"""
        if str(config.root) == "/":
            raise RuntimeError("Cannot build in root directory.")

        if config.clean:
            if config.root.exists():
                config.logger.warning(f"[{config.config_file}] Cleaning root: {config.root.resolve()}")
                rmtree(config.root, ignore_errors=True)

        if bases := getattr(config, "bases"):
            for base in bases:
                config.logger.info(
                    f"[{config.config_file}] Copying base root to build root: {base.root.resolve()} -> {config.root.resolve()}"
                )
                copytree(base.root.resolve(), config.root.resolve(), dirs_exist_ok=True, symlinks=True)

        if parent := getattr(config, "parent"):
            if config.copy_parent:
                config.logger.info(
                    f"[{config.config_file}] Copying parent root to branch root: {parent.root.resolve()} -> {config.root.resolve()}"
                )
                copytree(parent.root.resolve(), config.root.resolve(), dirs_exist_ok=True, symlinks=True)
        config.check_dir("root")
        config.check_dir("config_root", create=False)

    def perform_emerge(self, config):
        """Performs the emerge command for the current config"""
        if not getattr(config, "packages", None):
            config.logger.debug(f"[{config.config_file}] No packages to build")
            config.built = True
            return

        emerge_args = config.get_emerge_args()
        config.set_portage_env()
        config.logger.debug(f"[{config.config_file}] Emerge args: {emerge_args}")
        ret = run(["emerge", *emerge_args], capture_output=True)
        if ret.returncode:
            config.logger.error(f"Config: {config}")
            emerge_info = run(["emerge", "--info"], capture_output=True)
            config.logger.info(f"Emerge info:\n{emerge_info.stdout.decode()}")
            raise RuntimeError(
                f"Failed to run emerge with args: {emerge_args}\n{ret.stdout.decode()}\n{ret.stderr.decode()}"
            )
        config.built = True

    def build(self, config):
        """Builds all bases and branches under the current config
        Then builds the packages in the config"""
        self.build_bases(config=config)
        self.prepare_build(config=config)
        self.perform_emerge(config=config)
        self.build_branches(config=config)

    def build_tree(self):
        """Builds the tree"""
        self.logger.info(f"Building tree from: {self.config.config_file}")
        self.build(config=self.config)
