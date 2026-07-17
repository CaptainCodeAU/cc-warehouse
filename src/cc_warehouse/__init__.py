"""cc-warehouse: content-addressed, immutable warehouse for AI conversation sessions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cc-warehouse")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"
