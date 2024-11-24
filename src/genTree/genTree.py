from shutil import copytree
from subprocess import run

from zenlib.logging import loggify

from .genTreeConfig import GenTreeConfig


@loggify
class GenTree:
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    def build_branches(self, config):
        """Builds the branches under the current branch"""
        if branches := config.branches:
            for branch_name, branch_config in branches.items():
                self.logger.info(f"Building branch: {branch_name}")
                self.build_branch(config=branch_config)
                if branch_config.copy_branches:
                    self.logger.info(
                        f"Copying branch root to parent root: {branch_config.root.resolve()} -> {config.root.resolve()}"
                    )
                    copytree(branch_config.root, config.root, dirs_exist_ok=True)

    def build_branch(self, config=None):
        """Builds all branches under the current branch
        Then builds the branch itself."""
        config.prepare_build()
        self.build_branches(config=config)
        if not getattr(config, "packages", None):
            return
        emerge_args = config.get_emerge_args()
        config.set_portage_env()
        self.logger.debug(f"Emerge args: {emerge_args}")
        run(["emerge", *emerge_args])

    def build(self, config=None):
        """Builds the tree"""
        config = config or self.config
        self.logger.info(f"Building tree at: {config.root.resolve()}")
        self.build_branch(config=config)
