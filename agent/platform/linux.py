"""Linux platform implementation."""

import logging
import subprocess
from typing import Optional

from .base import PlatformBase

log = logging.getLogger(__name__)


class LinuxPlatform(PlatformBase):
    """Linux-specific implementations using X11 tools."""

    @property
    def name(self) -> str:
        return "linux"

    def lock_screen(self) -> bool:
        """Lock screen using loginctl or xdg-screensaver."""
        # Try loginctl first (works on systemd systems)
        try:
            result = subprocess.run(
                ["loginctl", "lock-session"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Screen locked via loginctl")
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Fallback to xdg-screensaver
        try:
            result = subprocess.run(
                ["xdg-screensaver", "lock"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Screen locked via xdg-screensaver")
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        log.error("Failed to lock screen")
        return False

    def unlock_screen(self) -> bool:
        """Unlock screen - not directly possible on Linux without password."""
        log.warning("Screen unlock not supported on Linux")
        return False

    def shutdown(self, delay: int = 0) -> bool:
        """Shutdown using systemctl."""
        try:
            if delay > 0:
                # Use shutdown command for delayed shutdown
                minutes = max(1, delay // 60)
                result = subprocess.run(
                    ["shutdown", "-h", f"+{minutes}"],
                    capture_output=True,
                    timeout=5,
                )
            else:
                result = subprocess.run(
                    ["systemctl", "poweroff"],
                    capture_output=True,
                    timeout=5,
                )
            if result.returncode == 0:
                log.info(f"Shutdown initiated (delay={delay}s)")
                return True
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log.error(f"Shutdown failed: {e}")
        return False

    def restart(self, delay: int = 0) -> bool:
        """Restart using systemctl."""
        try:
            if delay > 0:
                minutes = max(1, delay // 60)
                result = subprocess.run(
                    ["shutdown", "-r", f"+{minutes}"],
                    capture_output=True,
                    timeout=5,
                )
            else:
                result = subprocess.run(
                    ["systemctl", "reboot"],
                    capture_output=True,
                    timeout=5,
                )
            if result.returncode == 0:
                log.info(f"Restart initiated (delay={delay}s)")
                return True
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log.error(f"Restart failed: {e}")
        return False

    def cancel_shutdown(self) -> bool:
        """Cancel pending shutdown."""
        try:
            result = subprocess.run(
                ["shutdown", "-c"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Shutdown cancelled")
                return True
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log.error(f"Cancel shutdown failed: {e}")
        return False

    def get_active_window(self) -> Optional[str]:
        """Get active window title using xdotool."""
        try:
            # Get active window ID
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    def get_idle_seconds(self) -> int:
        """Get idle time using xprintidle."""
        try:
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                # xprintidle returns milliseconds
                ms = int(result.stdout.strip())
                return ms // 1000
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass
        return 0

    def show_warning(self, title: str, message: str) -> None:
        """Show warning popup using zenity."""
        try:
            subprocess.Popen(
                [
                    "zenity",
                    "--warning",
                    f"--title={title}",
                    f"--text={message}",
                    "--width=300",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info(f"Warning shown: {title}")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log.error(f"Failed to show warning: {e}")
