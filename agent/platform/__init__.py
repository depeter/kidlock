"""Platform-specific implementations."""

import sys

from .base import PlatformBase

if sys.platform == "win32":
    from .windows import WindowsPlatform as Platform
else:
    from .linux import LinuxPlatform as Platform


def get_platform() -> PlatformBase:
    """Get the appropriate platform implementation."""
    return Platform()


__all__ = ["get_platform", "Platform", "PlatformBase"]
