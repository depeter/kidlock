"""Linux platform implementation."""

import logging
import subprocess

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

    def get_active_window(self) -> str | None:
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

    def _get_user_session_id(self, username: str) -> str | None:
        """Get the session ID for a user from loginctl."""
        try:
            result = subprocess.run(
                ["loginctl", "list-sessions", "--no-legend"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    session_id = parts[0]
                    user = parts[2]
                    if user == username:
                        return session_id
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    def _get_user_display(self, username: str) -> str | None:
        """Get the DISPLAY for a user's session."""
        session_id = self._get_user_session_id(username)
        if not session_id:
            return None

        try:
            result = subprocess.run(
                ["loginctl", "show-session", session_id, "-p", "Display"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            line = result.stdout.strip()
            if line.startswith("Display=") and len(line) > 8:
                return line.split("=", 1)[1]
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    def get_user_idle_seconds(self, username: str) -> int:
        """Get idle time for a user's X session using xprintidle."""
        display = self._get_user_display(username)
        if not display:
            return 0

        try:
            # Get user's uid for XAUTHORITY path
            uid_result = subprocess.run(
                ["id", "-u", username],
                capture_output=True,
                text=True,
                timeout=5,
            )
            uid = uid_result.stdout.strip()

            # Run xprintidle as the user with their DISPLAY
            env = {
                "DISPLAY": display,
                "XAUTHORITY": f"/run/user/{uid}/gdm/Xauthority",
            }
            # Try common Xauthority locations
            xauth_paths = [
                f"/run/user/{uid}/gdm/Xauthority",
                f"/home/{username}/.Xauthority",
                f"/run/user/{uid}/.Xauthority",
            ]
            for xauth in xauth_paths:
                env["XAUTHORITY"] = xauth
                result = subprocess.run(
                    ["sudo", "-u", username, "xprintidle"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
                if result.returncode == 0:
                    # xprintidle returns milliseconds
                    ms = int(result.stdout.strip())
                    return ms // 1000
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass
        return 0

    def is_session_locked(self, username: str) -> bool:
        """Check if user's session is locked via loginctl."""
        session_id = self._get_user_session_id(username)
        if not session_id:
            return False

        try:
            result = subprocess.run(
                ["loginctl", "show-session", session_id, "-p", "LockedHint"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            line = result.stdout.strip()
            if line == "LockedHint=yes":
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return False

    def get_user_active_window(self, username: str) -> str | None:
        """Get active window title for a user's session using xdotool."""
        display = self._get_user_display(username)
        if not display:
            return None

        try:
            # Get user's uid for XAUTHORITY path
            uid_result = subprocess.run(
                ["id", "-u", username],
                capture_output=True,
                text=True,
                timeout=5,
            )
            uid = uid_result.stdout.strip()

            # Try common Xauthority locations
            xauth_paths = [
                f"/run/user/{uid}/gdm/Xauthority",
                f"/home/{username}/.Xauthority",
                f"/run/user/{uid}/.Xauthority",
            ]
            for xauth in xauth_paths:
                env = {
                    "DISPLAY": display,
                    "XAUTHORITY": xauth,
                }
                result = subprocess.run(
                    ["sudo", "-u", username, "xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
                if result.returncode == 0:
                    return result.stdout.strip() or None
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None
