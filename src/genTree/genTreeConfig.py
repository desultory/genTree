from pathlib import Path
from tomllib import load

from zenlib.types import validatedDataclass, NoDupFlatList


@validatedDataclass
class GenTreeConfig:
    required_config = ["root", "packages"]
    config_file: Path = "config.toml"
    emerge_log_dir: Path = "emerge_logs"
    portage_logdir: Path = "portage_logs"
    config: dict = None
    root: Path = None
    config_root: Path = None
    packages: list = None
    pkgdir: Path = None
    portage_tmpdir: Path = None

    def __post_init__(self, *args, **kwargs):
        self.load_config(self.config_file)
        self.process_kwargs(kwargs)
        self.validate_config()

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
            setattr(self, key, value)

    def validate_config(self):
        """Ensures all required config is set"""
        for key in self.required_config:
            if not getattr(self, key):
                raise ValueError(f"Missing required config: {key}")
