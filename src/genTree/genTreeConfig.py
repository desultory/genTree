from os import environ
from pathlib import Path
from tomllib import load
from typing import Optional, Union

from zenlib.types import validatedDataclass
from zenlib.util import handle_plural, pretty_print

from .genTreeTarFilter import GenTreeTarFilter
from .use_flags import UseFlags

SYSTEM_PACKAGES = [
    "app-arch/xz-utils",
    "sys-devel/gnuconfig",
    "app-shells/bash",
    "sys-apps/coreutils",
    "sys-libs/readline",
    "sys-apps/util-linux",
    "sys-apps/systemd-utils",
    "sys-fs/udev-init-scripts",
    "sys-libs/pam",
    "sys-auth/pambase",
    "app-arch/bzip2",
    "sys-devel/gcc",
    "sys-devel/gcc-config",
    "sys-apps/gawk",
    "sys-apps/attr",
    "sys-apps/grep",
    "app-arch/gzip",
    "sys-apps/findutils",
    "sys-apps/kmod",
    "sys-apps/sed",
    "sys-apps/less",
    "sys-fs/e2fsprogs",
    "sys-process/psmisc",
    "sys-devel/patch",
    "dev-build/make",
    "net-misc/iputils",
    "net-misc/wget",
    "sys-apps/which",
    "sys-process/procps",
    "sys-apps/elfix",
    "app-admin/eselect",
    "sys-apps/iproute2",
    "sys-apps/man-pages",
    "app-arch/tar",
    "dev-lang/python",
    "dev-lang/python-exec",
    "dev-lang/python-exec-conf",
    "dev-python/ensurepip-pip",
    "sys-libs/ncurses",
    "dev-python/gentoo-common",
    "sys-apps/gentoo-functions",
    "sys-apps/portage",
]

ENV_VAR_DIRS = ["emerge_log_dir", "portage_logdir", "pkgdir", "portage_tmpdir"]
ENV_VAR_STRS = ["use"]

INHERITED_CONFIG = [*ENV_VAR_DIRS, "clean_build", "rebuild", "layer_dir", "base_build_dir", "config_root"]


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
    depclean: bool = True  # runs emerge --depclean --with-bdeps=n after pulling packages
    remove_system: bool = False  # Removes system packages from the layer
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
    use: UseFlags = None
    # portage args
    config_root: Path = None
    # Tar filters
    tar_filter_dev: bool = True
    tar_filter_man: bool = True
    tar_filter_docs: bool = True
    tar_filter_include: bool = True
    tar_filter_completions: bool = True
    tar_filter_vardbpkg: bool = False

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
        return GenTreeTarFilter(logger=self.logger, **filter_args)

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
            if key in ["name", "logger", "use", "bases"]:
                continue
            setattr(self, key, value)

        self.load_use()

        self.bases = []
        for base in self.config.get("bases", []):
            self.add_base(base)

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
                    self.logger.debug("Creating directory: %s", path)
                    path.mkdir(parents=True)
                else:
                    raise FileNotFoundError(f"Directory does not exist: {path}")

    def get_emerge_args(self):
        """Gets emerge args for the current config"""
        args = ["--root", str(self.root)]
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
