from os import environ
from pathlib import Path
from tomllib import load
from typing import Optional, Union

from zenlib.types import validatedDataclass
from zenlib.util import colorize, handle_plural, pretty_print

from .gen_tree_tar_filter import GenTreeTarFilter
from .portage_types import EmergeBools, PortageFlags
from .whiteout_filter import WhiteoutFilter

ENV_VAR_INHERITED = ["features", "binpkg_format"]
ENV_VARS = [*ENV_VAR_INHERITED, "use"]
PORTAGE_STRS = ["jobs"]

INHERITED_CONFIG = [
    *ENV_VAR_INHERITED,
    "seed",
    "clean_build",
    "rebuild",
    "profile",
    "profile_repo",
]

CHILD_RESTRICTED = [
    "seed",
    "seed_dir",
    "_seed_dir",
    "build_dir",
    "_build_dir",
    "pkgdir",
    "_pkgdir",
    "config_dir",
    "_config_dir",
    "confroot",
]


def find_config(config_file):
    """Finds a config file included in the config module"""
    module_dir = Path(__file__).parent / "config"
    config = module_dir / Path(config_file).with_suffix(".toml")
    if not config.exists():
        raise FileNotFoundError(f"Config file not found: {config}")
    return config


@validatedDataclass
class GenTreeConfig:
    name: str = None  # The name of the config layer
    seed: str = None  # Seed name
    config_file: Path = None  # Path to the config file
    config: dict = None  # The config dictionary
    parent: Optional["GenTreeConfig"] = None
    bases: list = None  # List of base layer configs
    depclean: bool = False  # runs emerge --depclean --with-bdeps=n after pulling packages
    packages: list = None  # List of packages to install on the layer
    unmerge: list = None  # List of packages to unmerge on the layer
    clean_build: bool = True  # Cleans the layer build dir before copying base layers
    rebuild: bool = False  # Rebuilds the layer from scratch
    inherit_use: bool = False  # Inherit USE flags from the parent
    inherit_config: bool = False  # Inherit the config overlay from the parent
    # The following directories can only be set in the top level config
    conf_root: Path = "~/.local/share/genTree"  # The root of the genTree config
    _seed_dir: Path = None  # Directory where seeds are read from and used
    _build_dir: Path = None  # Directory where builds are performed and stored
    _config_dir: Path = None  # Directory where config overlays are stored
    _pkgdir: Path = None  # Directory where packages are stored
    config_overlay: str = None  # The config overlay to use, a directory in the config dir
    # Profiles can be set in any config and are applied before the emerge
    profile: str = "default/linux/amd64/23.0"
    profile_repo: str = "gentoo"
    archive_extension: str = ".tar"
    output_file: Path = None  # Override the output file
    # Other environment variables
    use: PortageFlags = None
    features: PortageFlags = None
    binpkg_format: str = "gpkg"
    # portage args
    jobs: int = 8
    emerge_bools: EmergeBools = None
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

    def on_conf_root(self, path):
        return Path(self.conf_root).expanduser().resolve() / path

    @property
    def pkgdir(self):
        if self._pkgdir:
            return self._pkgdir.expanduser().resolve()
        else:
            return self.on_conf_root("pkgdir")

    @property
    def build_dir(self):
        if self._build_dir:
            return self._build_dir.expanduser().resolve()
        else:
            return self.on_conf_root("builds")

    @property
    def seed_dir(self):
        if self._seed_dir:
            return self._seed_dir.expanduser().resolve()
        else:
            return self.on_conf_root("seeds")

    @property
    def config_dir(self):
        if self._config_dir:
            return self._config_dir.expanduser().resolve()
        else:
            return self.on_conf_root("config")

    @property
    def overlay_root(self):
        return Path("/builds") / self.name

    @property
    def lower_root(self):
        return self.overlay_root.with_name(f"{self.name}_lower")

    @property
    def work_root(self):
        return self.overlay_root.with_name(f"{self.name}_work")

    @property
    def upper_root(self):
        return self.overlay_root.with_name(f"{self.name}_upper")

    @property
    def config_mount(self):
        return self.sysroot / "config"

    @property
    def build_mount(self):
        return self.sysroot / "builds"

    @property
    def sysroot(self):
        return self.seed_dir / f"{self.seed}_sysroot"

    @property
    def upper_seed_root(self):
        return self.sysroot.with_name(f"{self.seed}_upper")

    @property
    def seed_root(self):
        return self.sysroot.with_name(f"{self.seed}")

    @property
    def work_seed_root(self):
        return self.sysroot.with_name(f"{self.seed}_work")

    @property
    def layer_archive(self):
        if self.output_file:
            return Path("/builds") / self.output_file
        return self.overlay_root.with_suffix(self.archive_extension)

    @property
    def tar_filter(self):
        filter_args = {}
        for f_name in [a.replace("tar_filter_", "") for a in self.__dataclass_fields__ if a.startswith("tar_filter_")]:
            filter_args[f"filter_{f_name}"] = getattr(self, f"tar_filter_{f_name}")
        return GenTreeTarFilter(logger=self.logger, **filter_args)

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
        if self.inherit_config:
            if "config_overlay" in self.config:
                raise ValueError(
                    "Config inheritance is set but config_overlay is already defined: %s", self.config["config_overlay"]
                )
            self.config_overlay = self.parent.config_overlay

    def process_kwargs(self, kwargs):
        """Process kwargs to set config values"""
        for key, value in kwargs.items():
            self.logger.debug("Setting attribute from kwargs: %s=%s", key, value)
            setattr(self, key, value)

    def load_config(self, config_file):
        """Read the config file, load it into self.config, set all config values as attributes"""
        from . import DEFAULT_FEATURES

        config = Path(config_file)
        if not config.exists():
            raise FileNotFoundError(f"Config file does not exist: {config_file}")

        with open(config, "rb") as f:
            self.config = load(f)

        self.name = self.config.get("name", config.stem)
        self.logger = self.logger.parent.getChild(self.name) if self.logger.parent else self.logger.getChild(self.name)
        self.logger.debug(f"[{config_file}] Loaded config: {self.config}")

        if getattr(self, "parent"):
            for restricted in CHILD_RESTRICTED:
                if restricted in self.config:
                    raise ValueError(f"Cannot set {restricted} in a child config")
            self.inherit_parent()
        elif "seed" not in self.config:
            raise ValueError("Seed must be set in the top level config")

        for key, value in self.config.items():
            if key in ["name", "emerge_bools", "logger", "use", "features", "bases", "whiteouts"]:
                continue
            setattr(self, key, value)

        self.features = PortageFlags(self.config.get("features", DEFAULT_FEATURES))
        self.load_use()
        self.load_emerge_bools()

        self.bases = []
        for base in self.config.get("bases", []):
            self.add_base(base)

        self.whiteouts = self.config.get("whiteouts", [])
        self.opaques = self.config.get("opaques", [])

    def load_emerge_bools(self):
        """Loads emerge boolean flags from the config"""
        from copy import deepcopy

        from . import DEFAULT_EMERGE_BOOLS

        self.emerge_bools = deepcopy(DEFAULT_EMERGE_BOOLS)
        if emerge_bools := self.config.get("emerge_bools"):
            self.emerge_bools.update(emerge_bools)
            self.logger.debug("Loaded emerge boolean flags: %s", self.emerge_bools)

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

    @handle_plural
    def check_dir(self, dirname, create=True):
        """Checks if a directory exists,
        if create is True, creates it if it doesn't exist
        otherwise raises FileNotFoundError"""
        if dirname := getattr(self, dirname):
            path = Path(dirname).expanduser().resolve()
            if not path.exists():
                if create:
                    self.logger.debug("Creating directory: %s", path)
                    path.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"Directory does not exist: {path}")

    def set_portage_profile(self):
        """Sets the portage profile in the sysroot"""
        self.logger.info(
            "[%s] Setting portage profile: %s", colorize(self.profile_repo, "yellow"), colorize(self.profile, "blue")
        )

        profile_sym = Path("/etc/portage/make.profile")
        if profile_sym.exists(follow_symlinks=False):
            profile_sym.unlink()

        profile_sym.symlink_to(
            Path(f"../../var/db/repos/{self.profile_repo}/profiles/{self.profile}"), target_is_directory=True
        )
        self.logger.debug("Set portage profile symlink: %s -> %s", profile_sym, profile_sym.resolve())

    def get_emerge_args(self):
        """Gets emerge args for the current config"""
        args = ["--root", str(self.overlay_root)]
        for str_arg in PORTAGE_STRS:
            if getattr(self, str_arg):
                args.extend([f"--{str_arg.replace('_', '-')}", str(getattr(self, str_arg))])
        args += [*str(self.emerge_bools).split(), *self.packages]
        return args

    def set_portage_env(self):
        """Sets portage environment variables based on the config"""
        for env in ENV_VARS:
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
