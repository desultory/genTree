from os import environ
from subprocess import run

from zenlib.logging import loggify
from zenlib.util import handle_plural

from .genTreeConfig import GenTreeConfig


@loggify
class GenTree:
    ENV_VARS = ["emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    @handle_plural
    def _check_dir(self, dirname, create=False, config=None):
        config = config or self.config
        if test_dir:= getattr(config, dirname):
            if not test_dir.exists():
                if create:
                    test_dir.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"[{dirname}] Directory does not exist: {test_dir}")

    def prepare_build(self, config):
        self.logger.debug(f"Preparing build for config: {config}")
        if not config.root.exists():
            config.root.mkdir(parents=True)
        self._check_dir("config_root", config=config)

    def get_emerge_args(self, config):
        """Gets a list of emerge args based on the config"""
        args = ["--root", str(config.root.resolve())]
        if config_root:= config.config_root:
            args.extend(["--config-root", str(config_root.resolve())])
        args += [*config.packages]
        return args

    def set_portage_env(self, config):
        """Sets environment variables based on the config"""
        for env_dir in self.ENV_VARS:
            self._check_dir(env_dir, create=True, config=config)
            env_name = env_dir.upper()
            env_path = getattr(config, env_dir).resolve()
            self.logger.debug("Setting environment variable: %s=%s", env_name, env_path)
            environ[env_name] = str(env_path)

    def check_emerge_info(self):
        """ Runs emerge --info to check the environment"""
        output = run(["emerge", "--info"], capture_output=True)
        self.emerge_info = output.stdout.decode()

    def build_branches(self, config=None):
        """Builds the branches of the tree"""
        if branches := config.branches:
            for branch_name, branch_config in branches.items():
                self.logger.info(f"Building branch: {branch_name}")
                self.build_branch(config=branch_config)

    def build_branch(self, config=None):
        """Builds a single branch"""
        self.prepare_build(config=config)
        self.build_branches(config=config)
        if not getattr(config, "packages", None):
            return
        emerge_args = self.get_emerge_args(config=config)
        self.set_portage_env(config=config)
        self.logger.debug(f"Emerge args: {emerge_args}")
        run(["emerge", *emerge_args])

    def build(self, config=None):
        """Builds the tree"""
        config = config or self.config
        self.logger.info(f"Building tree at: {config.root.resolve()}")
        self.build_branch(config=config)

