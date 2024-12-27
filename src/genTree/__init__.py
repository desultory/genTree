from .genTree import GenTree
from .types import EmergeBools

__all__ = ["EmergeBools", "GenTree"]

# Some bools don't support y/n, just --bool
PORTAGE_PLAIN_BOOLS = ["nodeps", "oneshot"]

DEFAULT_EMERGE_BOOLS = EmergeBools(
    {
        "verbose": True,  # Extra verbosity is nice
        "nodeps": False,  # Dependencies are typically needed
        "usepkg": True,  # Use binary packages when available
        "with_bdeps": False,  # Don't include build dependencies
    }
)

DEFAULT_EMERGE_ARGS = {
    "jobs": 8,  # Number of jobs to run in parallel
}

DEFAULT_FEATURES = [
    "buildpkg",  # Build binary packages
    "binpkg-multi-instance",  # Allow multiple versions of binary packages
    "parallel-fetch",  # Fetch multiple files at once
    "parallel-install",  # Install multiple packages at once
    "-ebuild-locks",
    "-merge-wait",
    "-merge-sync",
]

DEFAULT_TAR_FILTER_OPTIONS = {
    "whiteout": True,
    "dev": True,
    "man": True,
    "docs": True,
    "include": True,
    "charmaps": True,
    "locales": False,
    "completions": True,
    "vardbpkg": False,
}

DEFAULT_CLEAN_FILTER_OPTIONS = {
    #    "whiteout": True,
    #    "dev": True,
    "man": True,
    "docs": True,
    "include": True,
    "charmaps": True,
    "completions": True,
    "locales": False,
    "vardbpkg": False,
}
