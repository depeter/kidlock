"""Desktop notification helper for Kidlock agent."""

import logging
import os
import subprocess
from typing import Optional

log = logging.getLogger(__name__)


class Notifier:
    """Sends desktop notifications to users."""

    # Notification urgency levels for notify-send
    URGENCY_LOW = "low"
    URGENCY_NORMAL = "normal"
    URGENCY_CRITICAL = "critical"

    @staticmethod
    def _get_user_display(username: str) -> Optional[str]:
        """Get the DISPLAY environment variable for a logged-in user."""
        try:
            # Find user's display from their session
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
                        # Get display for this session
                        show_result = subprocess.run(
                            ["loginctl", "show-session", session_id, "-p", "Display"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        display_line = show_result.stdout.strip()
                        if display_line.startswith("Display=") and len(display_line) > 8:
                            return display_line.split("=", 1)[1]
            return None
        except Exception as e:
            log.debug(f"Could not get display for {username}: {e}")
            return None

    @staticmethod
    def _get_user_dbus(username: str) -> Optional[str]:
        """Get the DBUS_SESSION_BUS_ADDRESS for a logged-in user."""
        try:
            # Try to find the dbus address from the user's session
            result = subprocess.run(
                ["su", "-", username, "-c", "echo $DBUS_SESSION_BUS_ADDRESS"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            addr = result.stdout.strip()
            if addr:
                return addr

            # Fallback: construct from user ID
            uid_result = subprocess.run(
                ["id", "-u", username],
                capture_output=True,
                text=True,
                timeout=5,
            )
            uid = uid_result.stdout.strip()
            if uid:
                return f"unix:path=/run/user/{uid}/bus"
            return None
        except Exception as e:
            log.debug(f"Could not get DBUS for {username}: {e}")
            return None

    @classmethod
    def send_notification(
        cls,
        username: str,
        title: str,
        message: str,
        urgency: str = URGENCY_NORMAL,
        icon: str = "dialog-warning",
        timeout_ms: int = 10000,
    ) -> bool:
        """Send a desktop notification to a specific user.

        Args:
            username: The user to notify
            title: Notification title
            message: Notification body
            urgency: low, normal, or critical
            icon: Icon name or path
            timeout_ms: Time to show notification (0 = until dismissed)

        Returns:
            True if notification was sent successfully
        """
        display = cls._get_user_display(username)
        dbus_addr = cls._get_user_dbus(username)

        if not display:
            # Default fallback
            display = ":0"

        if not dbus_addr:
            # Try to find it from procfs for the user's processes
            try:
                uid_result = subprocess.run(
                    ["id", "-u", username],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                uid = uid_result.stdout.strip()
                dbus_addr = f"unix:path=/run/user/{uid}/bus"
            except Exception:
                pass

        env = os.environ.copy()
        env["DISPLAY"] = display
        if dbus_addr:
            env["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr

        try:
            # Use sudo to run notify-send as the target user
            cmd = [
                "sudo", "-u", username,
                "notify-send",
                "--urgency", urgency,
                "--icon", icon,
                "--expire-time", str(timeout_ms),
                "--app-name", "Kidlock",
                title,
                message,
            ]

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                timeout=10,
            )

            if result.returncode == 0:
                log.debug(f"Sent notification to {username}: {title}")
                return True
            else:
                log.warning(f"notify-send failed for {username}: {result.stderr.decode()}")
                return False

        except subprocess.TimeoutExpired:
            log.warning(f"Notification to {username} timed out")
            return False
        except Exception as e:
            log.error(f"Failed to send notification to {username}: {e}")
            return False

    @classmethod
    def send_time_warning(cls, username: str, minutes_left: int) -> bool:
        """Send a time warning notification to a user."""
        if minutes_left <= 0:
            title = "Time's Up!"
            message = "Your screen time is up. Logging out now..."
            urgency = cls.URGENCY_CRITICAL
            icon = "dialog-error"
            timeout = 5000
        elif minutes_left == 1:
            title = "1 Minute Left!"
            message = "Time to save your work!"
            urgency = cls.URGENCY_CRITICAL
            icon = "dialog-warning"
            timeout = 0  # Stay until dismissed
        elif minutes_left <= 5:
            title = f"{minutes_left} Minutes Left"
            message = "Almost out of time - save your work!"
            urgency = cls.URGENCY_CRITICAL
            icon = "dialog-warning"
            timeout = 15000
        else:
            title = f"{minutes_left} Minutes Left"
            message = f"You have {minutes_left} minutes of screen time remaining."
            urgency = cls.URGENCY_NORMAL
            icon = "dialog-information"
            timeout = 10000

        return cls.send_notification(
            username=username,
            title=title,
            message=message,
            urgency=urgency,
            icon=icon,
            timeout_ms=timeout,
        )

    @classmethod
    def send_schedule_warning(cls, username: str) -> bool:
        """Send a warning that scheduled hours are ending."""
        return cls.send_notification(
            username=username,
            title="Allowed Hours Ending",
            message="Your allowed screen time hours are ending soon.",
            urgency=cls.URGENCY_NORMAL,
            icon="dialog-information",
            timeout_ms=10000,
        )

    @classmethod
    def send_paused_notification(cls, username: str, paused: bool) -> bool:
        """Send notification about timer pause state."""
        if paused:
            title = "Timer Paused"
            message = "Your screen time timer has been paused."
            icon = "media-playback-pause"
        else:
            title = "Timer Resumed"
            message = "Your screen time timer is now running."
            icon = "media-playback-start"

        return cls.send_notification(
            username=username,
            title=title,
            message=message,
            urgency=cls.URGENCY_NORMAL,
            icon=icon,
            timeout_ms=5000,
        )

    @classmethod
    def send_bonus_time_notification(cls, username: str, minutes: int) -> bool:
        """Send notification about bonus time added."""
        return cls.send_notification(
            username=username,
            title="Bonus Time!",
            message=f"You've been given {minutes} extra minutes of screen time!",
            urgency=cls.URGENCY_NORMAL,
            icon="face-smile",
            timeout_ms=10000,
        )

    @classmethod
    def send_request_submitted(cls, username: str) -> bool:
        """Send notification that time request was submitted."""
        return cls.send_notification(
            username=username,
            title="Request Sent",
            message="Your request for more time has been sent to your parent.",
            urgency=cls.URGENCY_NORMAL,
            icon="mail-send",
            timeout_ms=5000,
        )

    @classmethod
    def send_request_approved(cls, username: str, minutes: int) -> bool:
        """Send notification that time request was approved."""
        return cls.send_notification(
            username=username,
            title="Request Approved!",
            message=f"Your request was approved! You got {minutes} extra minutes.",
            urgency=cls.URGENCY_NORMAL,
            icon="emblem-ok",
            timeout_ms=10000,
        )

    @classmethod
    def send_request_denied(cls, username: str) -> bool:
        """Send notification that time request was denied."""
        return cls.send_notification(
            username=username,
            title="Request Denied",
            message="Your request for more time was denied.",
            urgency=cls.URGENCY_NORMAL,
            icon="dialog-error",
            timeout_ms=10000,
        )
