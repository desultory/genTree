from pathlib import Path
from tomllib import load

from zenlib.types import validatedDataclass
from zenlib.util import handle_plural


@validatedDataclass
class GenTreeConfig:
    required_config = ["root", "emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
    config_file: Path = None
    # Environment variables
    emerge_log_dir: Path = "emerge_logs"
    portage_logdir: Path = "portage_logs"
    pkgdir: Path = "pkgdir"
    portage_tmpdir: Path = "portage_tmpdir"
    branches: dict = None
    config: dict = None
    root: Path = None
    config_root: Path = None
    packages: list = None
    _branch: bool = False

    def __post_init__(self, *args, **kwargs):
        print(GenTreeConfig.branches)
        # If _branch is set, we are creating a branch, load kwargs under the config file
        if kwargs.pop("_branch", False):
            self.process_kwargs(kwargs)
            self.load_config(self.config_file)
        else:
            self.load_config(self.config_file or kwargs.get("config_file"))
            self.process_kwargs(kwargs)
        self.validate_config()

    @handle_plural
    def add_branch(self, branch: Path):
        """Adds a branch to the config
        A branch is a config file which inherits config from the parent config file
        """
        branch = Path(branch)
        if branch.suffix != ".toml":
            raise ValueError(f"Branch file must be a toml file: {branch}")

        branch_name = branch.stem
        if branch_name in self.branches:
            raise ValueError(f"Branch already exists: {branch_name}")

        self.logger.debug("Adding branch: %s", branch_name)
        self.branches[branch_name] = GenTreeConfig(**self.generate_branch_base(branch))

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

        for key, value in self.config.items():
            if key == "logger":
                self.logger.error("Cannot override logger from config file")
                continue
            if key == "branches":
                if not getattr(self, "branches"):
                    self.branches = {}
                self.add_branch(value)
                continue
            setattr(self, key, value)

    def validate_config(self):
        """Ensures all required config is set"""
        for key in self.required_config:
            if not getattr(self, key):
                raise ValueError(f"Missing required config: {key}")

    def generate_branch_base(self, branch_config: Path):
        """Returns a dict of the base config for a branch"""
        config = self.__dict__.copy()
        config.pop("branches")
        config.pop("config")
        config["config_file"] = branch_config
        config["_branch"] = True
        self.logger.warning("Branch base config: %s", config)
        return config
