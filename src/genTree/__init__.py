from .genTree import GenTree

__all__ = ["GenTree"]

# Some bools don't support y/n, just --bool
PORTAGE_PLAIN_BOOLS = ["nodeps", "oneshot"]
