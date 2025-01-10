from copy import deepcopy
from dataclasses import field
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
]:  # For "default configs", later-parsed attributes overwrite previous ones
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
CPU_FLAG_VARS = [f"cpu_flags_{arch}" for arch in ["x86", "arm", "ppc"]]
COMMON_FLAGS = ["cflags", "cxxflags", "fcflags", "fflags"]  # The variable common flags should append to
ENV_VAR_INHERITED = [*COMMON_FLAGS, *CPU_FLAG_VARS, "binpkg_format"]
ENV_VARS = [*ENV_VAR_INHERITED, "use", "features"]

NO_DEFAULT_LOOKUP = [
    "name",  # Should be unique to each config
    "config_file",  # ''
    "build_tag",  # Used as a config lookup/identifier, cannot be set as a default
    "parent",  # Only inherited
    "bases",  # No sense in this being a default
    "whiteouts",  # Handled by filters
    "opaques",  # ''
    "packages",  # Should be unique per tree, no sense in a default
    "unmerge",  # ''
]

INHERITED_CONFIG = [
    "seed",  # Must be set in the top level config, cannot be set in a child
    "crossdev_target",  # ''
    "build_tag",  # ''
    "package_tag",  # ''
    "clean_build",  # Makes sense to inherit, but overrides can be set in a child
    "crossdev_use_env",  # ''
    "rebuild",  # ''
    "profile",  # ''
    "profile_repo",  # ''
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
    "repo_dir",
    "_repo_dir",
    "conf_root",
    "output_file",
    "refilter",
    "_buildname",
    "build_tag",
    "package_tag",
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
    _buildname: str = None  # Custom build name to use
    build_tag: str = None  # Tag name to use for the build
    config_file: Path = None  # Path to the config file
    config: dict = None  # The internal config dictionary
    parent: Optional["GenTreeConfig"] = None  # Parent config object
    bases: list = field(default_factory=list)  # List of base layer configs, set in parent when a child is added
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
    _repo_dir: Path = None  # Directory where user repos are stored
    output_file: Path = None  # Override the output file for the final archive
    package_tag: str = None  # Tag to use for the package directory, uses the build_tag if not set
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
    crossdev_use_env: bool = False  # Use common/compiler flags from the env for crossdev
    crossdev_env: dict = None  # Environment variables to set for crossdev
    # bind mounts
    bind_system_repos: bool = False  # bind /var/db/repos on the config root
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
        pkgdir = "pkgdir"
        if self.package_tag:
            pkgdir += f"_{self.package_tag}"
        elif self.build_tag:
            pkgdir += f"_{self.build_tag}"
        if self.crossdev_target:
            pkgdir += f"_{self.crossdev_target}"
        return self.on_conf_root(pkgdir)

    @property
    def pkgdir_mount(self):
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
    def repo_dir(self):
        if self._repo_dir:
            return self._repo_dir.expanduser().resolve()
        else:
            return self.on_conf_root("repos")

    @property
    def buildname(self):
        if self._buildname:
            return self._buildname
        buildname = self.seed
        if self.build_tag:
            buildname += f"-{self.build_tag}"
        if self.crossdev_target:
            buildname += f"-{self.crossdev_target}"
        buildname += f"-{self.name}"
        return buildname

    @property
    def overlay_root(self):
        return Path("/builds") / self.buildname

    @property
    def lower_root(self):
        return self.overlay_root.with_name(f".{self.buildname}_lower")

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
    def seed_root(self):
        return self.sysroot.with_name(f"{self.seed}")

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
        if not self.config_file:
            if self.crossdev_target:
                return self.crossdev_target
            return self.seed
        elif self.config_file.is_relative_to(Path(__file__).parent):
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
        """Gets defaults set in the DEFAULT_CONFIG.
        Prioritze config from:
            defualt.seed.build_tag.attr
            default.seed.attr
            default.attr
        Additioanal args are used to get sub-elements in dictionaries
        A default arg, used when no value was found, can be set with the 'default' kwarg
        """
        val = None
        if seed_overrides := DEFAULT_CONFIG.get("default", {}).get(self.seed):
            if build_overrides := seed_overrides.get(self.build_tag):
                val = build_overrides.get(attr)  # Get the build tag override if it exists
            if val is None:  # Try to get the seed override if no build tag override is set
                val = seed_overrides.get(attr)  # Get the seed override if it exists
        val = val or DEFAULT_CONFIG.get(attr)  # Get the default value if no seed override is set

        if val and subattrs:
            for subattr in subattrs:
                val = val.get(subattr, {})
        return val or default

    def __getattribute__(self, attr):
        """Try to get the attribute normally, if it's None, try the default config"""
        if attr.startswith("_") or attr in NO_DEFAULT_LOOKUP:
            return super().__getattribute__(attr)

        val = super().__getattribute__(attr)
        if val is None:
            if attr == "seed":
                return DEFAULT_CONFIG.get("seed")  # Seed is used in a lookup in get_default
            self.logger.debug("Getting default value for %s", attr)
            default = self.get_default(attr)
            if default is not None:
                return default
            self.logger.debug("No default value found for %s", attr)
            NO_DEFAULT_LOOKUP.append(attr)
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
            bases = self.bases
            self.bases = []
            self.add_base(bases)

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
        self.load_defaults(DEF_ARGS)  # load defaults
        self.load_env()

    @handle_plural
    def load_defaults(self, argname):
        """ Loads default values from the config file
        Uses this value if no value is set in the config"""
        if default := self.get_default(argname):
            default = deepcopy(default)
        else:
            default = {}
        setattr(self, argname, default | self.config.get(argname, {}))

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
            if key in ["name", "logger", "env", "crossdev_env", "bases", "whiteouts", "opaques", *DEF_ARGS]:
                continue  # Don't set these attributes directly
            setattr(self, key, value)

        add_bases = self.bases or []
        add_bases.extend(self.config.get("bases", []))
        self.bases = []
        self.add_base(add_bases)

        self.whiteouts = self.config.get("whiteouts", set())
        self.opaques = self.config.get("opaques", set())

    def inherit_defaults(self):
        """Load inherited defaults for the top level config"""
        for attr in INHERITED_CONFIG:
            if val := self.get_default(attr):
                self.logger.debug("Inheriting default config value: %s=%s", attr, val)
                setattr(self, attr, val)

    def get_env(self, attr, default=None):
        """Gets an environment variable from the config.
        Uses the main env dict, or crossdev_env if a crossdev target is set
        If a crossdev target is set, and crossdev_use_env is False, don't use the standard value
        """
        val = self.config.get("env", {}).get(attr)
        def_val = self.get_default("env", attr, default=default)
        if self.crossdev_target:
            if not self.crossdev_use_env and attr in [*ENV_VAR_INHERITED, "common_flags"]:
                def_val = self.get_default("crossdev_env", attr, default=default)
            else:  # Allow using the standard env if crossdev_use_env is set
                def_val = self.get_default("crossdev_env", attr, default=def_val)
            if env := self.config.get("crossdev_env"):
                val = env.get(attr) or val if self.crossdev_use_env else None  # Set the crossdev env if it exists
        return val or def_val

    def inherit_parent_env(self):
        """Inherit environment variables from the parent config, or use the default value"""
        for env in ENV_VAR_INHERITED:
            parent_value = self.parent.env.get(env) if self.parent else ""
            if env_value := self.get_env(env, default=parent_value):
                self.env[env] = env_value
            elif (default := self.get_default("env", env)) and self.inherit_env:
                self.logger.debug("Using default value for %s: %s", env, default)
                self.env[env] = default

    def load_env(self):
        """Loads environment variables from the config.
        Features are inherited by default
        USE flags are inherited if inherit_use is set"""
        use = PortageFlags(self.get_env("use", default=""))
        if (parent := self.parent) and self.inherit_use:
            use |= parent.env["use"]
        self.env = {"use": use}

        features = PortageFlags(self.get_env("features", default=""))
        if (parent := self.parent) and self.inherit_features:
            features |= PortageFlags(parent.env["features"])
        self.env["features"] = features
        self.inherit_parent_env()

        # Process common flags, pop common_flags from the env dict, apply to each type
        if common_flags := self.get_env("common_flags"):
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
        for env in ENV_VARS:
            env_value = self.env.get(env)
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
