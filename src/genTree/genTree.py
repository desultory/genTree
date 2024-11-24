from os import environ
from subprocess import run

from zenlib.logging import loggify
from zenlib.util import handle_plural, pretty_print

from .genTreeConfig import GenTreeConfig


@loggify
class GenTree:
    ENV_VARS = ["emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
    def __init__(self, config_file="config.toml", *args, **kwargs):
        self.config = GenTreeConfig(config_file=config_file, logger=self.logger, **kwargs)

    @handle_plural
    def _check_dir(self, dirname, create=False):
        if test_dir:= getattr(self.config, dirname):
            if not test_dir.exists():
                if create:
                    test_dir.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"[{dirname}] Directory does not exist: {test_dir}")

    def prepare_build(self):
        if not self.config.root.exists():
            self.config.root.mkdir(parents=True)
        self._check_dir("config_root")

    def get_emerge_args(self):
        """Gets a list of emerge args based on the config"""
        args = ["--root", str(self.config.root.resolve())]
        if config_root:= self.config.config_root:
            args.extend(["--config-root", str(config_root.resolve())])
        args += [*self.config.packages]
        return args

    def set_portage_env(self):
        """Sets environment variables based on the config"""
        for env_dir in self.ENV_VARS:
            self._check_dir(env_dir, create=True)
            environ[env_dir.upper()] = str(getattr(self.config, env_dir).resolve())

    def check_emerge_info(self):
        """ Runs emerge --info to check the environment"""
        output = run(["emerge", "--info"], capture_output=True)
        self.emerge_info = output.stdout.decode()

    def build(self):
        """Builds the tree"""
        self.prepare_build()
        self.logger.info(f"Building tree at: {self.config.root.resolve()}")
        self.logger.info(f"Packages: {pretty_print(self.config.packages)}")
        emerge_args = self.get_emerge_args()
        self.set_portage_env()
        self.check_emerge_info()
        self.logger.debug(f"Emerge args: {emerge_args}")
        run(["emerge", *emerge_args])

