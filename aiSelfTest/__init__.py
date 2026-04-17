"""Source-tree compatibility wrapper for the installable aiSelfTest package."""

from .aiSelfTest import create_app, main
from .aiSelfTest.version import __version__

__all__ = ["__version__", "create_app", "main"]
