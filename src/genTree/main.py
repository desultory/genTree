#!/usr/bin/env python3

from zenlib.util import get_kwargs

from .genTree import GenTree

def main():
    arguments = [
            {"flags": ["-c", "--config"], "help": "Path to the configuration file.", "action": "store"},
            {"flags": ["--root"], "help": "Set the emerge ROOT target rootfs path.", "action": "store"},
            {"flags": ["--config-root"], "help": "Set the config root for portage.", "action": "store"},
            ]

    kwargs = get_kwargs(package=__package__, description="Generates filesystem trees with portage.", arguments=arguments)
    genTree = GenTree(**kwargs)
    genTree.build()
