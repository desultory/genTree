#!/usr/bin/env python3

from os import getuid
from pathlib import Path
from shutil import copytree
from tarfile import TarFile

from zenlib.util import get_kwargs, nsexec

from .genTree import GenTree
from .gen_tree_tar_filter import GenTreeTarFilter


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


def import_seed():
    """ Imports a seed archive to ~.local/share/genTree/seeds/<name>"""
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
    ]

    kwargs = get_kwargs(
        package="genTree-import-seed", description="Imports a seed archive to ~/.local/share/genTree/seeds/<name>", arguments=arguments
    )
    logger = kwargs.pop("logger")
    seed = Path(kwargs.pop("seed"))
    name = kwargs.pop("name", seed.stem.split(".")[0])

    if getuid() != 0:
        seeds_dir = Path("~/.local/share/genTree/seeds").expanduser().resolve()
    else:
        seeds_dir = Path("/var/lib/genTree/seeds")

    seed_dir = seeds_dir / name

    if seed_dir.exists():
        raise FileExistsError(f"Seed already exists: {seed_dir}")

    if seed.is_dir() and seed.exists():
        copytree(seed, seed_dir)
    else:
        with TarFile.open(seed) as tar:
            tar.extractall(seed_dir, filter=GenTreeTarFilter(logger=logger, filter_dev=True))

    logger.info(f"Seed imported: {seed_dir}")

