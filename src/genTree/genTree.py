from shutil import copytree
from subprocess import run

from zenlib.logging import loggify

from .genTreeConfig import GenTreeConfig


@loggify
class GenTree:
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    def build_bases(self, config):
        """ Builds the bases for the current config"""
        if bases := config.bases:
            for base in bases:
                self.logger.info(f"Building base: {base}")
                self.build_config(config=base)

    def build_branches(self, config):
        """Builds the branches under the current branch"""
        if branches := config.branches:
            for branch in branches:
                self.logger.info(f"Building branch: {branch}")
                self.build_config(config=branch)

    def build_config(self, config):
        """Builds all bases and branches under the current config
        Then builds the packages in the config"""
        self.build_bases(config=config)
        config.prepare_build()
        self.build_branches(config=config)
        if not getattr(config, "packages", None):
            return
        emerge_args = config.get_emerge_args()
        config.set_portage_env()
        self.logger.debug(f"Emerge args: {emerge_args}")
        ret = run(["emerge", *emerge_args], capture_output=True)
        if ret.returncode:
            self.logger.error(f"Config: {config}")
            emerge_info = run(["emerge", "--info"], capture_output=True)
            self.logger.info(f"Emerge info:\n{emerge_info.stdout.decode()}")
            raise RuntimeError(f"Failed to run emerge with args: {emerge_args}\n{ret.stdout.decode()}\n{ret.stderr.decode()}")
        config.built = True

    def build(self, config=None):
        """Builds the tree"""
        config = config or self.config
        self.logger.info(f"Building tree at: {config.root.resolve()}")
        self.build_config(config=config)
