from os import environ
from pathlib import Path
from tomllib import load
from typing import Optional

from zenlib.types import validatedDataclass
from zenlib.util import handle_plural, pretty_print

from .use_flags import UseFlags

ENV_VAR_DIRS = ["emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
ENV_VAR_STRS = ["use"]

INHERITED_CONFIG = [*ENV_VAR_DIRS, "clean", "root", "config_root"]


@validatedDataclass
class GenTreeConfig:
    required_config = ["root", *ENV_VAR_DIRS]
    config_file: Path = None
    parent: Optional["GenTreeConfig"] = None
    bases: list = None
    depclean: bool = True  # runs emerge --depclean --with-bdeps=n after pulling packages
    built: bool = False  # Set to true if the config has completed an emerge
    config: dict = None
    packages: list = None
    clean: bool = True
    inherit_use: bool = False  # Inherit USE flags from the parent
    # Environment variable directories
    emerge_log_dir: Path = "emerge_logs"
    portage_logdir: Path = "portage_logs"
    pkgdir: Path = "pkgdir"
    portage_tmpdir: Path = "portage_tmpdir"
    # Other environment variables
    use: UseFlags = None
    # portage args
    root: Path = None
    config_root: Path = None

    def __post_init__(self, *args, **kwargs):
        # If _branch is set, we are creating a branch, load kwargs under the config file
        if getattr(self, "parent"):
            self.inherit_parent()
            self.load_config(self.config_file)
        else:
            self.load_config(self.config_file or kwargs.get("config_file"))
            self.process_kwargs(kwargs)
        self.validate_config()

    @handle_plural
    def add_base(self, base: Path):
        """Adds a base config to the config
        A base is a config which is used as an image base for the current config
        """
        base = Path(base)
        if base.suffix != ".toml":
            raise ValueError(f"Base file must be a toml file: {base}")
        self.bases.append(GenTreeConfig(logger=self.logger, config_file=base, parent=self))

    def inherit_parent(self):
        """Inherits config from the parent object"""
        for attr in INHERITED_CONFIG:
            setattr(self, attr, getattr(self.parent, attr))

    def process_kwargs(self, kwargs):
        """Process kwargs to set config values"""
        for key, value in kwargs.items():
            setattr(self, key, value)

    def load_config(self, config_file):
        """Read the config file, load it into self.config, set all config values as attributes"""
        config = Path(config_file)
        if not config.exists():
            raise FileNotFoundError(f"Config file does not exist: {config_file}")

        with open(config, "rb") as f:
            self.config = load(f)
        self.logger.debug(f"[{config_file}] Loaded config: {self.config}")

        self.load_use()
        for key, value in self.config.items():
            if key in ["logger", "use", "inherit_use"]:
                continue
            elif key == "bases":
                if not getattr(self, "bases"):
                    self.bases = []
                self.add_base(value)
                continue
            setattr(self, key, value)

    def load_use(self):
        """Loads USE flags from the config, inheriting them from the parent if inherit_use is True"""
        if inherit_use := self.config.get("inherit_use"):
            self.inherit_use = inherit_use
        parent_use = getattr(self.parent, "use") if self.inherit_use else set()
        config_use = UseFlags(self.config.get("use", ""))
        if self.inherit_use:
            self.use = parent_use | config_use
        else:
            self.use = config_use

    def validate_config(self):
        """Ensures all required config is set"""
        for key in self.required_config:
            if not getattr(self, key):
                raise ValueError(f"Missing required config: {key}")

    @handle_plural
    def check_dir(self, dirname, create=True):
        """Checks if a directory exists,
        if create is True, creates it if it doesn't exist
        otherwise raises FileNotFoundError"""
        if dirname := getattr(self, dirname):
            path = Path(dirname)
            if not path.exists():
                if create:
                    path.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"Directory does not exist: {path}")

    def get_emerge_args(self):
        """Gets emerge args for the current config"""
        args = ["--root", str(self.root.resolve())]
        if config_root := self.config_root:
            args.extend(["--config-root", str(config_root.resolve())])
        args += [*self.packages]
        return args

    def set_portage_env(self):
        """Sets portage environment variables based on the config"""
        for env_dir in ENV_VAR_DIRS:
            self.check_dir(env_dir)
            env_name = env_dir.upper()
            env_path = getattr(self, env_dir).resolve()
            self.logger.debug("Setting environment variable: %s=%s", env_name, env_path)
            environ[env_name] = str(env_path)

        if use_flags := self.use:
            self.logger.info("Setting USE flags: %s", use_flags)
            environ["USE"] = str(use_flags)

    def __str__(self):
        out_dict = {attr: getattr(self, attr) for attr in self.__dataclass_fields__}
        out_dict.pop("parent", None)
        out_dict.pop("bases", None)
        return pretty_print(out_dict)
