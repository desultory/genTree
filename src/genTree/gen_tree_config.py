from os import environ
from pathlib import Path
from tomllib import load
from typing import Optional, Union

from zenlib.types import validatedDataclass
from zenlib.util import handle_plural, pretty_print

from .gen_tree_tar_filter import GenTreeTarFilter
from .portage_types import FlagBool, PortageFlags
from .whiteout_filter import WhiteoutFilter

DEFAULT_FEATURES = [
    "buildpkg",
    "binpkg-multi-instance",
    "parallel-fetch",
    "parallel-install",
    "-ebuild-locks",
    "-merge-wait",
    "-merge-sync",
]

ENV_VAR_DIRS = ["emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
ENV_VAR_INHERITED = [*ENV_VAR_DIRS, "features"]
ENV_VARS = [*ENV_VAR_INHERITED, "use"]
PORTAGE_BOOLS = ["nodeps", "with_bdeps", "usepkg"]
PORTAGE_STRS = ["jobs", "config_root"]

INHERITED_CONFIG = [*ENV_VAR_INHERITED, "clean_build", "rebuild", "layer_dir", "base_build_dir", "config_root"]


def find_config(config_file):
    """Finds a config file included in the config module"""
    module_dir = Path(__file__).parent / "config"
    config = module_dir / Path(config_file).with_suffix(".toml")
    if not config.exists():
        raise FileNotFoundError(f"Config file not found: {config}")
    return config


@validatedDataclass
class GenTreeConfig:
    required_config = ["name", *ENV_VAR_DIRS]
    name: str = None  # The name of the config layer
    config_file: Path = None  # Path to the config file
    parent: Optional["GenTreeConfig"] = None
    bases: list = None  # List of base layer configs
    depclean: bool = False  # runs emerge --depclean --with-bdeps=n after pulling packages
    config: dict = None  # The config dictionary
    packages: list = None  # List of packages to install on the layer
    unmerge: list = None  # List of packages to unmerge on the layer
    clean_build: bool = True  # Cleans the layer build dir before copying base layers
    rebuild: bool = False  # Rebuilds the layer from scratch
    inherit_use: bool = False  # Inherit USE flags from the parent
    layer_dir: Path = "/var/lib/genTree/layers"
    archive_extension: str = ".tar"
    output_file: Path = None  # Override the output file
    base_build_dir: Path = "/var/lib/genTree/builds"
    # Environment variable directories
    emerge_log_dir: Path = "/var/lib/genTree/emerge_logs"
    portage_logdir: Path = "/var/lib/genTree/portage_logs"
    pkgdir: Path = "/var/lib/genTree/pkgdir"
    portage_tmpdir: Path = "/var/lib/genTree/portage_tmpdir"
    # Other environment variables
    use: PortageFlags = None
    features: PortageFlags = None
    binpkg_format: str = "gpkg"
    # portage args
    config_root: Path = "/var/lib/genTree/config_roots/default"
    jobs: int = 4
    with_bdeps: FlagBool = False
    usepkg: FlagBool = True
    verbose: bool = True
    nodeps: bool = False
    # bind mounts
    bind_system_repos: bool = True  # bind /var/db/repos on the config root
    system_repos: Path = "/var/db/repos"
    # Tar filters
    tar_filter_whiteout: bool = True  # Filter whiteout files
    tar_filter_dev: bool = True  # Filters character and block devices
    tar_filter_man: bool = True  # Filters manual pages
    tar_filter_docs: bool = True  # Filters documentation
    tar_filter_include: bool = True  # Filters included headers
    tar_filter_charmaps: bool = True  # Filters charmaps
    tar_filter_completions: bool = True  # Filters shell completions
    tar_filter_vardbpkg: bool = False  # Filters /var/db/pkg
    # whiteout
    whiteouts: list = None  # List of paths to "whiteout" in the lower layer
    opaques: list = None  # List of paths to "opaque" in the lower layer

    def __post_init__(self, *args, **kwargs):
        self.load_config(self.config_file or kwargs.get("config_file"))
        self.process_kwargs(kwargs)
        self.validate_config()

    @property
    def root(self):
        return self.base_build_dir.resolve() / self.name

    @property
    def lower_root(self):
        return self.base_build_dir.resolve() / f"{self.name}_lower"

    @property
    def work_root(self):
        return self.base_build_dir.resolve() / f"{self.name}_work"

    @property
    def upper_root(self):
        return self.base_build_dir.resolve() / f"{self.name}_upper"

    @property
    def layer_archive(self):
        return self.output_file or (self.layer_dir.resolve() / self.name).with_suffix(self.archive_extension)

    @property
    def tar_filter(self):
        filter_args = {}
        for f_name in [a.replace("tar_filter_", "") for a in self.__dataclass_fields__ if a.startswith("tar_filter_")]:
            filter_args[f"filter_{f_name}"] = getattr(self, f"tar_filter_{f_name}")
        return GenTreeTarFilter(owner=self, logger=self.logger, **filter_args)

    @property
    def whiteout_filter(self):
        return WhiteoutFilter(logger=self.logger, whiteouts=self.whiteouts, opaques=self.opaques)

    @property
    def file_display_name(self):
        if self.config_file.is_relative_to(Path(__file__).parent):
            return self.config_file.name
        return self.config_file

    @handle_plural
    def add_base(self, base: Union[str, Path]):
        """Adds a base is a config which is used as an image base for the current config"""
        if not str(base).endswith(".toml"):
            base = find_config(base)
        self.bases.append(GenTreeConfig(logger=self.logger, config_file=base, parent=self))

    def inherit_parent(self):
        """Inherits config from the parent object"""
        self.logger.log(5, "Inheriting config from parent: %s", self.parent)
        for attr in INHERITED_CONFIG:
            parent_val = getattr(self.parent, attr)
            self.logger.debug("Inheriting attribute: %s=%s", attr, parent_val)
            setattr(self, attr, parent_val)

    def process_kwargs(self, kwargs):
        """Process kwargs to set config values"""
        for key, value in kwargs.items():
            self.logger.debug("Setting attribute from kwargs: %s=%s", key, value)
            setattr(self, key, value)

    def load_config(self, config_file):
        """Read the config file, load it into self.config, set all config values as attributes"""
        config = Path(config_file)
        if not config.exists():
            raise FileNotFoundError(f"Config file does not exist: {config_file}")

        with open(config, "rb") as f:
            self.config = load(f)

        self.name = self.config["name"]
        self.logger = self.logger.parent.getChild(self.name) if self.logger.parent else self.logger.getChild(self.name)
        self.logger.debug(f"[{config_file}] Loaded config: {self.config}")

        if getattr(self, "parent"):
            self.inherit_parent()

        for key, value in self.config.items():
            if key in ["name", "logger", "use", "features", "bases", "whiteouts"]:
                continue
            setattr(self, key, value)

        self.features = PortageFlags(self.config.get("features", DEFAULT_FEATURES))
        self.load_use()

        self.bases = []
        for base in self.config.get("bases", []):
            self.add_base(base)

        self.whiteouts = self.config.get("whiteouts", [])
        self.opaques = self.config.get("opaques", [])

    def load_use(self):
        """Loads USE flags from the config, inheriting them from the parent if inherit_use is True"""
        if inherit_use := self.config.get("inherit_use"):
            self.inherit_use = inherit_use
        parent_use = getattr(self.parent, "use") if self.inherit_use else set()
        config_use = PortageFlags(self.config.get("use", ""))
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
                    self.logger.debug("Creating directory: %s", path)
                    path.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"Directory does not exist: {path}")

    def get_emerge_args(self):
        """Gets emerge args for the current config"""
        args = ["--root", str(self.root)]
        for str_arg in PORTAGE_STRS:
            if getattr(self, str_arg):
                args.extend([f"--{str_arg.replace('_', '-')}", str(getattr(self, str_arg))])
        for bool_arg in PORTAGE_BOOLS:
            if isinstance(getattr(self, bool_arg), FlagBool):
                args.append(f"--{bool_arg.replace('_', '-')}={getattr(self, bool_arg)}")
            elif getattr(self, bool_arg):
                args.append(f"--{bool_arg.replace('_', '-')}")
        args += [*self.packages]
        return args

    def set_portage_env(self):
        """Sets portage environment variables based on the config"""
        for env_dir in ENV_VAR_DIRS:
            self.check_dir(env_dir)

        for env in ENV_VARS:
            if env in ENV_VAR_DIRS:
                env_value = getattr(self, env).resolve()
            else:
                env_value = getattr(self, env)
            env = env.upper()
            if env_value is None or hasattr(env_value, "__len__") and len(env_value) == 0:
                self.logger.debug("Skipping unset environment variable: %s", env)
                continue
            self.logger.debug("Setting environment variable: %s=%s", env, env_value)
            environ[env] = str(env_value)

        if use_flags := self.use:
            self.logger.info("Setting USE flags: %s", use_flags)
            environ["USE"] = str(use_flags)

    def __str__(self):
        out_dict = {attr: getattr(self, attr) for attr in self.__dataclass_fields__}
        out_dict.pop("parent", None)
        out_dict.pop("bases", None)
        return pretty_print(out_dict)
