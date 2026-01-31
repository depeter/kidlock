"""Abstract base class for platform-specific implementations."""

from abc import ABC, abstractmethod
from typing import Optional


class PlatformBase(ABC):
    """Abstract interface for platform-specific operations."""

    @abstractmethod
    def lock_screen(self) -> bool:
        """Lock the screen. Returns True on success."""
        pass

    @abstractmethod
    def unlock_screen(self) -> bool:
        """Unlock the screen (if possible). Returns True on success."""
        pass

    @abstractmethod
    def shutdown(self, delay: int = 0) -> bool:
        """Shutdown the computer with optional delay in seconds."""
        pass

    @abstractmethod
    def restart(self, delay: int = 0) -> bool:
        """Restart the computer with optional delay in seconds."""
        pass

    @abstractmethod
    def cancel_shutdown(self) -> bool:
        """Cancel a pending shutdown/restart."""
        pass

    @abstractmethod
    def get_active_window(self) -> Optional[str]:
        """Get the title of the currently active window."""
        pass

    @abstractmethod
    def get_idle_seconds(self) -> int:
        """Get the number of seconds since last user input."""
        pass

    @abstractmethod
    def show_warning(self, title: str, message: str) -> None:
        """Show a warning popup to the user."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the platform name."""
        pass
