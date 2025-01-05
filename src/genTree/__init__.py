from .genTree import GenTree

__all__ = ["GenTree"]

# Some bools don't support y/n, just --bool
PORTAGE_PLAIN_BOOLS = ["nodeps", "oneshot"]


# for cmdline usage
COMMON_ARGS = [
    {
        "flags": ["-c", "--crossdev-target"],
        "help": "The crossdev toolchain type.",
        "action": "store",
    },
    {
        "flags": ["-p", "--profile"],
        "help": "The profile to use.",
        "action": "store",
    },
    {
        "flags": ["-t", "--build-tag"],
        "help": "The build tag to use.",
        "action": "store",
    }
]
