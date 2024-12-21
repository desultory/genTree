#!/usr/bin/env python3

from zenlib.util import get_kwargs

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
    genTree.build_tree()
