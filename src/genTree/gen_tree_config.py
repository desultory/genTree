from copy import deepcopy
from os import environ
from pathlib import Path
from subprocess import SubprocessError, run
from tomllib import load
from typing import Optional, Union

from zenlib.types import validatedDataclass
from zenlib.util import colorize, handle_plural, pretty_print

from .filters import BuildCleaner, GenTreeTarFilter, WhiteoutFilter
from .types import EmergeBools, PortageFlags

# Check load config from the package root/default.toml,
# Then check /etc/genTree/gentree.toml and ~/.config/genTree/gentree.toml

DEFAULT_CONFIG = {}
for config in [
    Path(__file__).parent / "default.toml",
    Path("/etc/genTree/config.toml"),
    Path("~/.config/genTree/config.toml").expanduser(),
]:  # For "default configs", top-level attributes overwrite previous ones
    # User supplied config is merged over the final DEFAULT_CONFIG
    if config.exists():
        with open(config, "rb") as f:
            config = load(f)
            for key, value in config.items():
                if key in DEFAULT_CONFIG and isinstance(value, dict):
                    DEFAULT_CONFIG[key] |= value
                elif key in DEFAULT_CONFIG and isinstance(value, list):
                    DEFAULT_CONFIG[key].extend(value)
                else:
                    DEFAULT_CONFIG[key] = value


DEF_ARGS = ["clean_filter_options", "tar_filter_options", "emerge_args", "emerge_bools"]
NO_DEFAULT_LOOKUP = ["name", "config_file", "parent", "bases", "whiteouts", "opaques"]
CPU_FLAG_VARS = [f"cpu_flags_{arch}" for arch in ["x86", "arm", "ppc"]]
COMMON_FLAGS = ["cflags", "cxxflags", "fcflags", "fflags"]  # The variable common flags should append to
ENV_VAR_INHERITED = [*COMMON_FLAGS, *CPU_FLAG_VARS, "binpkg_format", "common_flags"]
ENV_VARS = [*ENV_VAR_INHERITED, "use", "features"]

INHERITED_CONFIG = [
    "seed",
    "crossdev_target",
    "clean_build",
    "rebuild",
    "profile",
    "profile_repo",
]

CHILD_RESTRICTED = [
    "seed",
    "crossdev_target",
    "seed_dir",
    "_seed_dir",
    "build_dir",
    "_build_dir",
    "pkgdir",
    "_pkgdir",
    "config_dir",
    "_config_dir",
    "distfile_dir",
    "_distfile_dir",
    "conf_root",
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
    no_seed_overlay: bool = False  # Do not use a seed overlay, used for updates/upgrades
    config_file: Path = None  # Path to the config file
    config: dict = None  # The internal config dictionary
    parent: Optional["GenTreeConfig"] = None  # Parent config object
    bases: list = None  # List of base layer configs, set in parent when a child is added
    inherit_env: bool = True  # Inherit default environment variables from the parent
    inherit_features: bool = True  # Inherit default features from the parent
    inherit_use: bool = False  # Inherit USE flags from the parent
    inherit_config: bool = False  # Inherit the config overlay from the parent
    # The following directories can only be set in the top level config
    conf_root: Path = "~/.local/share/genTree"  # The root of the genTree config
    _seed_dir: Path = None  # Directory where seeds are read from and used
    _build_dir: Path = None  # Directory where builds are performed and stored
    _config_dir: Path = None  # Directory where config overlays are stored
    _pkgdir: Path = None  # Directory where packages are stored
    _distfile_dir: Path = None  # Directory where distfiles are stored
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
    seed_update_args: str = None  # Arguments to use when updating the seed
    # Crossdev stuff
    crossdev_target: str = None  # Crossdev target tuple
    crossdev_profile: str = None  # Profile override to use for crossdev
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
        elif self.crossdev_target:
            return self.on_conf_root(f"pkgdir_{self.crossdev_target}")
        else:
            return self.on_conf_root("pkgdir")

    @property
    def pkgdir_target(self):
        if self.crossdev_target:
            return self.sysroot / f"usr/{self.crossdev_target}/var/cache/binpkgs"
        return self.sysroot / "var/cache/binpkgs"

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
    def distfile_dir(self):
        if self._distfile_dir:
            return self._distfile_dir.expanduser().resolve()
        else:
            return self.on_conf_root("distfiles")

    @property
    def crossdev_repo_dir(self):
        return Path("/crossdev_repo")

    @property
    def buildname(self):
        if self.crossdev_target:
            return f"{self.seed}-{self.crossdev_target}-{self.name}"
        return f"{self.seed}-{self.name}"

    @property
    def overlay_root(self):
        return Path("/builds") / self.buildname

    @property
    def lower_root(self):
        return self.overlay_root.with_name(f".{self.buildname}_lower")

    @property
    def work_root(self):
        return self.overlay_root.with_name(f".{self.buildname}_work")

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
        if self.no_seed_overlay:
            return self.seed_dir / self.seed
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
        return self.sysroot.with_name(f".{self.seed}_work")

    @property
    def temp_seed_root(self):
        return self.sysroot.with_name(f".{self.seed}_temp")

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

    @property
    def emerge_cmd(self):
        return f"emerge-{self.crossdev_target}" if self.crossdev_target else "emerge"

    @property
    def emerge_profiles(self):
        cfgroot = f"/usr/{self.crossdev_target}" if self.crossdev_target else "/"
        old_root = environ.get("PORTAGE_CONFIGROOT")
        environ["PORTAGE_CONFIGROOT"] = cfgroot
        try:
            profles = run(["eselect", "profile", "list"], check=True, capture_output=True)
        except SubprocessError as e:
            raise ValueError(f"Failed to get profiles: {e}")
        if old_root:
            environ["PORTAGE_CONFIGROOT"] = old_root
        return profles.stdout.decode()

    def get_default(self, attr, *subattrs, default=None):
        """Gets defaults set in the DEFAULT_CONFIG, first using overrides for the seed
        then using global defaults.
        Additioanal args are used to get sub-elements in dictionaries"""
        val = DEFAULT_CONFIG.get(self.seed, {}).get(attr) or DEFAULT_CONFIG.get(attr)
        if subattrs:
            for subattr in subattrs:
                val = val.get(subattr, {})
        return val or default

    def __getattribute__(self, attr):
        """Try to get the attribute normally, if it's None, try the default config"""
        val = super().__getattribute__(attr)
        if val is None and attr not in NO_DEFAULT_LOOKUP and not attr.startswith("_"):
            if attr == "seed":
                return DEFAULT_CONFIG.get("seed")  # Seed is used in a lookup in get_default
            self.logger.debug("Getting default value for %s", attr)
            return self.get_default(attr)
        return val

    @handle_plural
    def add_base(self, base: Union[str, Path]):
        """Adds a base is a config which is used as an image base for the current config"""
        if not str(base).endswith(".toml"):
            base = find_config(base)
        self.bases.append(GenTreeConfig(logger=self.logger, config_file=base, parent=self))

    def __post_init__(self, *args, **kwargs):
        self.process_kwargs(kwargs)
        config_file = self.config_file or kwargs.get("config_file")
        if config_file:
            self.load_config(config_file)
        else:
            self.config = {}
            self.name = self.name or self.seed
            self.load_standard_config()

    def inherit_parent(self):
        """Inherits config from the parent object"""
        self.logger.log(5, "Inheriting config from parent: %s", self.parent)
        for attr in INHERITED_CONFIG:
            parent_val = getattr(self.parent, attr, self.get_default(attr))
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
        elif "seed" not in self.config and "seed" not in DEFAULT_CONFIG:
            raise ValueError("Seed must be set in the top level config")
        else:
            self.inherit_defaults()

        self.load_standard_config()
        for key, value in self.config.items():
            if key in ["name", "logger", "env", "bases", "whiteouts", "opaques", *DEF_ARGS]:
                continue  # Don't set these attributes directly
            setattr(self, key, value)

        self.bases = []
        for base in self.config.get("bases", []):
            self.add_base(base)

        self.whiteouts = self.config.get("whiteouts", set())
        self.opaques = self.config.get("opaques", set())

    def inherit_defaults(self):
        """Load inherited defaults for the top level config"""
        for attr in INHERITED_CONFIG:
            if val := self.get_default(attr):
                self.logger.debug("Inheriting default config value: %s=%s", attr, val)
                setattr(self, attr, val)

    @handle_plural
    def load_defaults(self, argname):
        if default := self.get_default(argname):
            default = deepcopy(default)
        else:
            default = {}
        setattr(self, argname, default | self.config.get(argname, {}))

    def load_env(self):
        """Loads environment variables from the config.
        Features are always inherited.
        USE flags are inherited if inherit_use is set"""

        use = PortageFlags(self.config.get("env", {}).get("use", ""))
        if self.inherit_use:
            use |= self.parent.env["use"]
        self.env = {"use": use}
        conf_features = self.config.get("env", {}).get("features", "")
        if parent_features := getattr(self.parent, "env", {}).get("features", set()):
            self.env["features"] = parent_features | PortageFlags(conf_features)
        elif self.inherit_features:
            self.env["features"] = PortageFlags(self.get_default("env", "features", default="")) | PortageFlags(
                conf_features
            )

        for env in ENV_VAR_INHERITED:
            parent_value = self.parent.env.get(env) if self.parent else ""
            if env_value := self.config.get("env", {}).get(env, parent_value):
                self.env[env] = env_value
            elif (default := self.get_default("env", env)) and self.inherit_env:
                self.logger.debug("Using default value for %s: %s", env, default)
                self.env[env] = default

        # Process common flags, pop common_flags from the env dict, apply to each type
        if common_flags := self.env.pop("common_flags", ""):
            for flag in COMMON_FLAGS:
                if flag not in self.env:
                    self.env[flag] = common_flags
                elif common_flags not in self.env[flag]:
                    self.env[flag] += " " + common_flags
                else:
                    self.logger.debug("Common flag already set: %s=%s", flag, self.env[flag])

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
        if not self.profile and not self.crossdev_profile:
            return self.logger.debug("No portage profile set")

        profile, profile_repo = self.profile, self.profile_repo
        profile_sym = Path("/etc/portage/make.profile")
        if self.crossdev_target:
            profile = self.crossdev_profile or self.profile
            profile_sym = Path(f"/usr/{self.crossdev_target}/etc/portage/make.profile")

        profile_target = Path(f"/var/db/repos/{profile_repo}/profiles/{profile}")
        if profile_sym.is_symlink() and profile_sym.resolve() == profile_target:
            return self.logger.debug("Portage profile already set: %s -> %s", profile_sym, profile_target)

        self.logger.info(
            " ~-~ [%s] Setting portage profile: %s",
            colorize(profile_repo, "yellow"),
            colorize(profile, "blue"),
        )

        if profile_sym.exists(follow_symlinks=False):
            profile_sym.unlink()

        if not profile_target.exists():
            self.logger.info(" -+- %s", self.emerge_profiles)
            raise FileNotFoundError(f"Portage profile not found: {profile_target}")

        profile_sym.symlink_to(profile_target, target_is_directory=True)
        self.logger.debug("Set portage profile symlink: %s -> %s", profile_sym, profile_sym.resolve())

    def set_portage_env(self):
        """Sets portage environment variables based on the config"""
        set_vars = ENV_VARS
        if self.crossdev_target:  # Dont't set
            remove_flags = COMMON_FLAGS + CPU_FLAG_VARS + ["common_flags"]
            for flag in remove_flags:
                if flag in set_vars:
                    self.logger.debug("Removing flag for crossdev: %s", flag)
                    set_vars.remove(flag)
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
