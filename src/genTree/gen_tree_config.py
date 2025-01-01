from copy import deepcopy
from importlib import import_module
from os import environ
from pathlib import Path
from tomllib import load
from typing import Optional, Union

from zenlib.types import validatedDataclass
from zenlib.util import colorize, handle_plural, pretty_print

from .filters import BuildCleaner, GenTreeTarFilter, WhiteoutFilter
from .types import EmergeBools, PortageFlags

DEF_ARGS = ["clean_filter_options", "tar_filter_options", "emerge_args"]
CPU_FLAG_VARS = [f"cpu_flags_{arch}" for arch in ["x86", "arm", "ppc"]]
ENV_VAR_INHERITED = [*CPU_FLAG_VARS, "binpkg_format"]
ENV_VARS = [*ENV_VAR_INHERITED, "use", "features"]

INHERITED_CONFIG = [
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
    "output_file",
    "refilter",
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
    seed: str = None  # Seed name, can only and must be set in the top level config
    config_file: Path = None  # Path to the config file
    config: dict = None  # The internel config dictionary
    parent: Optional["GenTreeConfig"] = None  # Parent config object
    bases: list = None  # List of base layer configs, set in parent when a child is added
    inherit_use: bool = False  # Inherit USE flags from the parent
    inherit_config: bool = False  # Inherit the config overlay from the parent
    # The following directories can only be set in the top level config
    conf_root: Path = "~/.local/share/genTree"  # The root of the genTree config
    _seed_dir: Path = None  # Directory where seeds are read from and used
    _build_dir: Path = None  # Directory where builds are performed and stored
    _config_dir: Path = None  # Directory where config overlays are stored
    _pkgdir: Path = None  # Directory where packages are stored
    output_file: Path = None  # Override the output file for the final archive
    # Profiles can be set in any config and are applied before the emerge
    profile: str = None  # The portage profile to use
    profile_repo: str = "gentoo"
    config_overlay: str = None  # The config overlay to use, a directory in the config dir
    # Archive configuration
    archive_extension: str = ".tar"
    # Environment variables
    env: dict = None  # Environment variables to set in the chroot
    # portage args
    rebuild: bool = False  # Rebuilds the layer from scratch
    depclean: bool = False  # runs emerge --depclean --with-bdeps=n after pulling packages
    packages: list = None  # List of packages to install on the layer
    unmerge: list = None  # List of packages to unmerge on the layer
    emerge_args: dict = None  # Emerge string arguments
    emerge_bools: EmergeBools = None  # Emerge boolean flags
    seed_update: bool = True  # Update the seed before building
    seed_update_args: str = "--jobs 8 --update --deep --newuse --changed-use --with-bdeps=y --usepkg=y @world"
    # bind mounts
    bind_system_repos: bool = True  # bind /var/db/repos on the config root
    system_repos: Path = "/var/db/repos"
    # Build cleaner
    clean_seed: bool = False  # Cleans the seed directory before chrooting
    ephemeral_seed: bool = False  # use a tmpfs for the seed overlay upper dir
    clean_build: bool = True  # Cleans the layer build dir before copying base layers
    clean_filter_options: dict = None  # Options for the clean filter
    tar_filter_options: dict = None  # Options for the tar filter
    refilter: bool = True  # Refilter the outermost layer
    # whiteout
    whiteouts: set = None  # List of paths to "whiteout" in the lower layer
    opaques: set = None  # List of paths to "opaque" in the lower layer

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
    def buildname(self):
        return f"{self.seed}-{self.name}"

    @property
    def overlay_root(self):
        return Path("/builds") / self.buildname

    @property
    def lower_root(self):
        return self.overlay_root.with_name(f"{self.buildname}_lower")

    @property
    def work_root(self):
        return self.overlay_root.with_name(f"{self.buildname}_work")

    @property
    def upper_root(self):
        return self.overlay_root.with_name(f"{self.buildname}_upper")

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
        if self.ephemeral_seed:
            return self.temp_seed_root / "upper"
        return self.sysroot.with_name(f"{self.seed}_upper")

    @property
    def seed_root(self):
        return self.sysroot.with_name(f"{self.seed}")

    @property
    def work_seed_root(self):
        if self.ephemeral_seed:
            return self.temp_seed_root / "work"
        return self.sysroot.with_name(f"{self.seed}_work")

    @property
    def temp_seed_root(self):
        return self.sysroot.with_name(f"{self.seed}_temp")

    @property
    def layer_archive(self):
        return self.overlay_root.with_suffix(self.archive_extension)

    @property
    def output_archive(self):
        if self.output_file:
            return Path("/builds") / self.output_file
        return self.overlay_root.with_stem(f"{self.buildname}-full").with_suffix(self.archive_extension)

    @property
    def tar_filter(self):
        return GenTreeTarFilter(logger=self.logger, **self.tar_filter_options)

    @property
    def whiteout_filter(self):
        return WhiteoutFilter(logger=self.logger, whiteouts=self.whiteouts, opaques=self.opaques)

    @property
    def cleaner(self):
        return BuildCleaner(logger=self.logger, **self.clean_filter_options)

    @property
    def file_display_name(self):
        if self.config_file.is_relative_to(Path(__file__).parent):
            return self.config_file.name
        return self.config_file

    @property
    def emerge_string_args(self):
        return [f"--{k}={v}" for k, v in self.emerge_args.items()]

    @property
    def emerge_bool_args(self):
        return str(self.emerge_bools).split()

    @property
    def emerge_flags(self):
        return ["--root", str(self.overlay_root), *self.emerge_string_args, *self.emerge_bool_args, *self.packages]

    @handle_plural
    def add_base(self, base: Union[str, Path]):
        """Adds a base is a config which is used as an image base for the current config"""
        if not str(base).endswith(".toml"):
            base = find_config(base)
        self.bases.append(GenTreeConfig(logger=self.logger, config_file=base, parent=self))

    def __post_init__(self, *args, **kwargs):
        config_file = self.config_file or kwargs.get("config_file")
        if config_file:
            self.load_config(config_file)
        else:
            self.config = {}
            self.load_standard_config()
        self.process_kwargs(kwargs)

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

    def load_standard_config(self):
        self.load_defaults(DEF_ARGS)  # load defaults from the package __init__
        self.load_env()
        self.load_emerge_bools()

    def load_config(self, config_file):
        """Read the config file, load it into self.config, set all config values as attributes"""
        config = Path(config_file)
        if not config.exists():
            raise FileNotFoundError(f"Config file does not exist: {config_file}")

        with open(config, "rb") as f:
            self.config = load(f)

        self.name = self.config.get("name", config.stem)
        self.logger = self.logger.parent.getChild(self.name) if self.logger.parent else self.logger.getChild(self.name)
        self.logger.debug(f"[{config_file}] Loaded config: {self.config}")

        if getattr(self, "parent"):  # Inherit the parent and restrict top-level only attributes
            for restricted in CHILD_RESTRICTED:
                if restricted in self.config:
                    raise ValueError(f"Cannot set {restricted} in a child config")
            self.inherit_parent()
        elif "seed" not in self.config:
            raise ValueError("Seed must be set in the top level config")

        self.load_standard_config()
        for key, value in self.config.items():
            if key in ["name", "emerge_bools", "logger", "env", "bases", "whiteouts", "opaques", *DEF_ARGS]:
                continue  # Don't set these attributes directly
            setattr(self, key, value)

        self.bases = []
        for base in self.config.get("bases", []):
            self.add_base(base)

        self.whiteouts = self.config.get("whiteouts", set())
        self.opaques = self.config.get("opaques", set())

    @handle_plural
    def load_defaults(self, argname):
        defaults = deepcopy(getattr(import_module("genTree"), f"default_{argname}".upper(), {}))
        setattr(self, argname, defaults | self.config.get(argname, {}))

    def load_emerge_bools(self):
        """Loads emerge boolean flags from the config"""
        from . import DEFAULT_EMERGE_BOOLS

        self.emerge_bools = deepcopy(DEFAULT_EMERGE_BOOLS)
        if emerge_bools := self.config.get("emerge_bools"):
            self.emerge_bools.update(emerge_bools)
            self.logger.debug("Loaded emerge boolean flags: %s", self.emerge_bools)

    def load_env(self):
        """Loads environment variables from the config.
        Features are always inherited.
        USE flags are inherited if inherit_use is set"""

        use = PortageFlags(self.config.get("env", {}).get("use", ""))
        if self.config.get("inherit_use", False):
            use |= self.parent.env["use"]
        self.env = {"use": use}
        if parent_features := getattr(self.parent, "env", {}).get("features", set()):
            self.env["features"] = parent_features | PortageFlags(self.config.get("features", ""))
        else:
            from . import DEFAULT_FEATURES

            self.env["features"] = DEFAULT_FEATURES | PortageFlags(self.config.get("features", ""))

        for env in ENV_VAR_INHERITED:
            parent_value = self.parent.env.get(env) if self.parent else ""
            if env_value := self.config.get("env", {}).get(env, parent_value):
                self.env[env] = env_value
            elif default := getattr(import_module("genTree"), f"default_{env}".upper(), ""):
                self.logger.debug("Using default value for %s: %s", env, default)
                self.env[env] = default

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
        if not self.profile:
            return self.logger.debug("No portage profile set")

        profile_sym = Path("/etc/portage/make.profile")
        profile_target = Path(f"../../var/db/repos/{self.profile_repo}/profiles/{self.profile}")
        if profile_sym.is_symlink() and profile_sym.resolve() == profile_target:
            return self.logger.debug("Portage profile already set: %s -> %s", profile_sym, profile_target)

        self.logger.info(
            " ~-~ [%s] Setting portage profile: %s",
            colorize(self.profile_repo, "yellow"),
            colorize(self.profile, "blue"),
        )

        if profile_sym.exists(follow_symlinks=False):
            profile_sym.unlink()

        profile_sym.symlink_to(profile_target, target_is_directory=True)
        self.logger.debug("Set portage profile symlink: %s -> %s", profile_sym, profile_sym.resolve())

    def set_portage_env(self):
        """Sets portage environment variables based on the config"""
        for env in ENV_VARS:
            env_value = getattr(self, "env", {}).get(env)
            env = env.upper()
            if env_value is None or hasattr(env_value, "__len__") and len(env_value) == 0:
                if env in environ:
                    self.logger.debug("Unsetting environment variable: %s", env)
                    environ.pop(env)
                continue
            self.logger.debug("Setting environment variable: %s=%s", env, env_value)
            environ[env] = str(env_value)

        if use := self.env.get("use"):
            self.logger.info(" ~+~ Environment USE flags: %s", colorize(use, "yellow"))

    def __str__(self):
        out_dict = {attr: getattr(self, attr) for attr in self.__dataclass_fields__}
        out_dict.pop("parent", None)
        out_dict.pop("bases", None)
        return pretty_print(out_dict)
