#!/usr/bin/env python3

from pathlib import Path
from shutil import copytree
from tarfile import TarFile

from zenlib.namespace import nsexec
from zenlib.util import get_kwargs

from .filters import GenTreeTarFilter
from .genTree import GenTree


def main():
    arguments = [
        {
            "flags": ["config_file"],
            "help": "Path to the configuration file.",
            "action": "store",
            "default": "config.toml",
        },
    ]

    kwargs = get_kwargs(
        package=__package__, description="Generates filesystem trees with portage.", arguments=arguments
    )
    genTree = GenTree(**kwargs)
    nsexec(genTree.build_tree)


def clean_builds():
    """Removes all build tarballs from the build directory."""
    arguments = [
        {
            "flags": ["build_root"],
            "help": "Root directory of the builds.",
            "action": "store",
            "default": "~/.local/share/genTree/builds",
            "nargs": "?",
        },
    ]

    kwargs = get_kwargs(
        package="genTree-clean-builds",
        description="Removes all build tarballs from the build directory.",
        arguments=arguments,
    )
    logger = kwargs.pop("logger")
    build_root = Path(kwargs.pop("build_root")).expanduser().resolve()
    logger.info(f"Cleaning build root: {build_root}")

    for build in build_root.iterdir():
        if build.is_file() and build.suffix == ".tar":
            logger.info(f"Removing build: {build}")
            build.unlink()


def update_seed():
    """Updates a seed"""
    arguments = [
        {
            "flags": ["seed"],
            "help": "Name of the seed.",
            "action": "store",
        },
        {
            "flags": ["seed_update_args"],
            "help": "Argument string to pass to the update function.",
            "action": "store",
            "nargs": "?",
        },
    ]
    kwargs = get_kwargs(package="genTree-update-seed", description="Updates a seed", arguments=arguments)
    genTree = GenTree(**kwargs)
    nsexec(genTree.update_seed)


def init_crossdev():
    """Initialized a crossdev environment for the specified seed."""
    arguments = [
        {
            "flags": ["seed"],
            "help": "Name of the seed.",
            "action": "store",
        },
        {
            "flags": ["crossdev_target"],
            "help": "The crossdev toolchain type.",
            "action": "store",
        },
    ]
    kwargs = get_kwargs(
        package="genTree-init-crossdev", description="Initializes a crossdev toolchain", arguments=arguments
    )
    crossdev_target = kwargs.pop("crossdev_target")
    genTree = GenTree(**kwargs)
    nsexec(genTree.init_crossdev, crossdev_target)


def import_seed():
    """Imports a seed archive to ~.local/share/genTree/seeds/<name>"""
    arguments = [
        {
            "flags": ["seed"],
            "help": "Path to the seed archive.",
            "action": "store",
        },
        {
            "flags": ["name"],
            "help": "Name of the seed.",
            "action": "store",
            "nargs": "?",
        },
        {
            "flags": ["conf_root"],
            "help": "Root directory of the configuration.",
            "action": "store",
            "default": "~/.local/share/genTree",
            "nargs": "?",
        },
    ]

    kwargs = get_kwargs(
        package="genTree-import-seed",
        description="Imports a seed archive to ~/.local/share/genTree/seeds/<name>",
        arguments=arguments,
    )
    logger = kwargs.pop("logger")
    seed = Path(kwargs.pop("seed"))
    name = kwargs.pop("name", seed.stem.split(".")[0])

    seeds_dir = Path(kwargs.pop("conf_root")).expanduser().resolve() / "seeds"
    logger.debug(f"Seeds directory: {seeds_dir}")
    seed_dir = seeds_dir / name
    logger.debug(f"Seed directory: {seed_dir}")

    if seed_dir.exists():
        raise FileExistsError(f"Seed already exists: {seed_dir}")

    if seed.is_dir() and seed.exists():
        logger.info(f"Copying seed directory: {seed} -> {seed_dir}")
        copytree(seed, seed_dir)
    else:
        with TarFile.open(seed) as tar:
            logger.info(f"Extracting seed archive: {seed} -> {seed_dir}")
            tar.extractall(seed_dir, filter=GenTreeTarFilter(logger=logger, dev=True))

    logger.info(f"[{name}] Seed imported: {seed_dir}")
