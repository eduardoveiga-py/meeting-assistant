"""Meeting Assistant application package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meeting-assistant")
except PackageNotFoundError:
    __version__ = "development"
