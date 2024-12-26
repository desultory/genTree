from .portage_types import PortageBools
from .genTree import GenTree


__all__ = ["PortageBools", "GenTree"]

# Some bools don't support y/n, just --bool
PORTAGE_PLAIN_BOOLS = ["nodeps"]

DEFAULT_PORTAGE_BOOLS = PortageBools(
        {
            "verbose": True,  # Extra verbosity is nice
            "nodeps": False,  # Dependencies are typically needed
            "usepkg": True,  # Use binary packages when available
            "with_bdeps": False,  # Don't include build dependencies
        }
        )

DEFAULT_FEATURES = [
        "buildpkg",  # Build binary packages
        "binpkg-multi-instance",  # Allow multiple versions of binary packages
        "parallel-fetch",  # Fetch multiple files at once
        "parallel-install",  # Install multiple packages at once
        "-ebuild-locks",
        "-merge-wait",
        "-merge-sync",
        ]
