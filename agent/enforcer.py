"""User session enforcement for Kidlock agent."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

from .config import ScheduleConfig, UserConfig

log = logging.getLogger(__name__)

STATE_DIR = Path("/var/lib/kidlock")
STATE_FILE = STATE_DIR / "state.json"
PAM_CHECK_SCRIPT = Path("/usr/local/bin/kidlock-pam-check")


class UserState:
    """Tracks state for a single user."""

    def __init__(self, username: str):
        self.username = username
        self.usage_minutes: int = 0
        self.last_usage_date: Optional[str] = None
        self.blocked: bool = False
        self.block_reason: str = ""
        # New fields for enhanced features
        self.paused: bool = False
        self.paused_at: Optional[str] = None  # ISO timestamp when paused
        self.bonus_minutes: int = 0  # Extra time for today
        self.warnings_sent: Set[int] = set()  # Warning thresholds already sent today
        # Idle detection (not persisted - runtime only)
        self.is_idle: bool = False
        # Time request (persisted)
        self.pending_request: Optional[dict] = None  # {id, minutes, reason, created_at}

    def to_dict(self) -> dict:
        return {
            "usage_minutes": self.usage_minutes,
            "last_usage_date": self.last_usage_date,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "paused": self.paused,
            "paused_at": self.paused_at,
            "bonus_minutes": self.bonus_minutes,
            "warnings_sent": list(self.warnings_sent),
            "pending_request": self.pending_request,
        }

    @classmethod
    def from_dict(cls, username: str, data: dict) -> "UserState":
        state = cls(username)
        state.usage_minutes = data.get("usage_minutes", 0)
        state.last_usage_date = data.get("last_usage_date")
        state.blocked = data.get("blocked", False)
        state.block_reason = data.get("block_reason", "")
        state.paused = data.get("paused", False)
        state.paused_at = data.get("paused_at")
        state.bonus_minutes = data.get("bonus_minutes", 0)
        state.warnings_sent = set(data.get("warnings_sent", []))
        state.pending_request = data.get("pending_request")
        return state


class Enforcer:
    """Enforces parental control rules on users."""

    def __init__(self):
        self._user_states: Dict[str, UserState] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                for username, user_data in data.get("users", {}).items():
                    self._user_states[username] = UserState.from_dict(username, user_data)
                log.info(f"Loaded state for {len(self._user_states)} users")
            except Exception as e:
                log.error(f"Failed to load state: {e}")

    def _save_state(self) -> None:
        """Persist state to disk."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "users": {
                username: state.to_dict()
                for username, state in self._user_states.items()
            }
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
            # Make readable by all users (for tray indicator)
            os.chmod(STATE_FILE, 0o644)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def get_user_state(self, username: str) -> UserState:
        """Get or create state for a user."""
        if username not in self._user_states:
            self._user_states[username] = UserState(username)
        return self._user_states[username]

    def get_logged_in_users(self) -> Set[str]:
        """Get set of currently logged-in users."""
        try:
            result = subprocess.run(
                ["who"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            users = set()
            for line in result.stdout.strip().split("\n"):
                if line:
                    users.add(line.split()[0])
            return users
        except Exception as e:
            log.error(f"Failed to get logged in users: {e}")
            return set()

    def is_within_schedule(self, schedule: ScheduleConfig) -> bool:
        """Check if current time is within allowed schedule."""
        now = datetime.now()
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        # Use weekend schedule for Saturday(5) and Sunday(6)
        schedule_str = schedule.weekend if weekday >= 5 else schedule.weekday

        try:
            start_str, end_str = schedule_str.split("-")
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
            current_time = now.time()

            return start_time <= current_time <= end_time
        except ValueError as e:
            log.error(f"Invalid schedule format '{schedule_str}': {e}")
            return True  # Allow on error

    def check_user(self, user_config: UserConfig) -> tuple[bool, str]:
        """Check if user should be allowed.

        Returns (allowed, reason).
        """
        state = self.get_user_state(user_config.username)
        today = date.today().isoformat()

        # Reset usage and bonus if new day
        if state.last_usage_date != today:
            state.usage_minutes = 0
            state.bonus_minutes = 0
            state.warnings_sent = set()
            state.last_usage_date = today
            self._save_state()

        # Check schedule
        if not self.is_within_schedule(user_config.schedule):
            return False, "Outside allowed hours"

        # Check daily limit (including bonus time)
        if user_config.daily_minutes > 0:
            total_allowed = user_config.daily_minutes + state.bonus_minutes
            if state.usage_minutes >= total_allowed:
                return False, "Daily time limit reached"

        return True, ""

    def add_usage(self, username: str, minutes: int) -> None:
        """Add usage time for a user."""
        state = self.get_user_state(username)
        today = date.today().isoformat()

        if state.last_usage_date != today:
            state.usage_minutes = 0
            state.last_usage_date = today

        state.usage_minutes += minutes
        self._save_state()
        log.debug(f"User {username} usage: {state.usage_minutes} minutes")

    def get_usage_minutes(self, username: str) -> int:
        """Get today's usage minutes for a user."""
        state = self.get_user_state(username)
        today = date.today().isoformat()

        if state.last_usage_date != today:
            return 0
        return state.usage_minutes

    def force_logout(self, username: str, reason: str) -> bool:
        """Force logout a user."""
        log.warning(f"Force logout {username}: {reason}")
        state = self.get_user_state(username)
        state.blocked = True
        state.block_reason = reason
        self._save_state()

        try:
            # Try loginctl first (cleanest method)
            result = subprocess.run(
                ["loginctl", "terminate-user", username],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                log.info(f"Terminated sessions for {username} via loginctl")
                return True

            # Fallback: kill all user processes
            result = subprocess.run(
                ["pkill", "-KILL", "-u", username],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                log.info(f"Killed processes for {username} via pkill")
                return True

            log.error(f"Failed to force logout {username}")
            return False

        except Exception as e:
            log.error(f"Error forcing logout {username}: {e}")
            return False

    def unblock_user(self, username: str) -> None:
        """Unblock a user (allow login again)."""
        state = self.get_user_state(username)
        state.blocked = False
        state.block_reason = ""
        self._save_state()
        log.info(f"Unblocked user {username}")

    def set_paused(self, username: str, paused: bool) -> None:
        """Set pause state for a user."""
        state = self.get_user_state(username)
        if paused and not state.paused:
            state.paused = True
            state.paused_at = datetime.now().isoformat()
            log.info(f"Paused timer for {username}")
        elif not paused and state.paused:
            state.paused = False
            state.paused_at = None
            log.info(f"Resumed timer for {username}")
        self._save_state()

    def is_paused(self, username: str) -> bool:
        """Check if timer is paused for a user."""
        state = self.get_user_state(username)
        return state.paused

    def check_pause_auto_resume(self, username: str, auto_resume_minutes: int) -> bool:
        """Check if pause should auto-resume. Returns True if resumed."""
        state = self.get_user_state(username)
        if not state.paused or not state.paused_at:
            return False

        try:
            paused_at = datetime.fromisoformat(state.paused_at)
            elapsed = datetime.now() - paused_at
            if elapsed >= timedelta(minutes=auto_resume_minutes):
                self.set_paused(username, False)
                log.info(f"Auto-resumed timer for {username} after {auto_resume_minutes} minutes")
                return True
        except Exception as e:
            log.error(f"Error checking pause auto-resume: {e}")

        return False

    def add_bonus_time(self, username: str, minutes: int) -> None:
        """Add bonus time for a user (for today only)."""
        state = self.get_user_state(username)
        state.bonus_minutes += minutes
        # Also unblock if they were blocked due to time limit
        if state.blocked and "limit" in state.block_reason.lower():
            state.blocked = False
            state.block_reason = ""
        self._save_state()
        log.info(f"Added {minutes} bonus minutes for {username} (total bonus: {state.bonus_minutes})")

    def get_time_remaining(self, username: str, daily_limit: int) -> int:
        """Get remaining minutes for today (including bonus time).

        Returns -1 if unlimited.
        """
        if daily_limit <= 0:
            return -1

        state = self.get_user_state(username)
        today = date.today().isoformat()

        if state.last_usage_date != today:
            return daily_limit  # Full time if new day

        total_allowed = daily_limit + state.bonus_minutes
        remaining = total_allowed - state.usage_minutes
        return max(0, remaining)

    def get_warnings_to_send(self, username: str, daily_limit: int, warning_thresholds: list) -> list:
        """Get list of warning thresholds that should be sent now.

        Returns list of minutes values that haven't been sent yet and should trigger now.
        """
        if daily_limit <= 0:
            return []

        state = self.get_user_state(username)
        remaining = self.get_time_remaining(username, daily_limit)

        warnings_to_send = []
        for threshold in warning_thresholds:
            if threshold not in state.warnings_sent and remaining <= threshold:
                warnings_to_send.append(threshold)

        return warnings_to_send

    def mark_warning_sent(self, username: str, threshold: int) -> None:
        """Mark a warning threshold as sent."""
        state = self.get_user_state(username)
        state.warnings_sent.add(threshold)
        self._save_state()

    def get_status(self, username: str, daily_limit: int) -> str:
        """Get current status string for a user."""
        state = self.get_user_state(username)
        logged_in = username in self.get_logged_in_users()

        if not logged_in:
            return "Offline"
        if state.blocked:
            return "Blocked"
        if state.paused:
            return "Paused"
        return "Playing"

    def get_bonus_minutes(self, username: str) -> int:
        """Get bonus minutes for a user."""
        state = self.get_user_state(username)
        return state.bonus_minutes

    def set_idle(self, username: str, is_idle: bool) -> None:
        """Set idle state for a user (not persisted)."""
        state = self.get_user_state(username)
        state.is_idle = is_idle

    def is_idle(self, username: str) -> bool:
        """Check if user is idle."""
        state = self.get_user_state(username)
        return state.is_idle

    def create_time_request(self, username: str, minutes: int, reason: str = "") -> dict:
        """Create a pending time request for a user.

        Returns the created request dict.
        """
        import uuid
        state = self.get_user_state(username)
        request = {
            "id": str(uuid.uuid4())[:8],
            "minutes": minutes,
            "reason": reason,
            "created_at": datetime.now().isoformat(),
        }
        state.pending_request = request
        self._save_state()
        log.info(f"Created time request for {username}: {minutes} minutes")
        return request

    def get_pending_request(self, username: str) -> Optional[dict]:
        """Get current pending request for a user."""
        state = self.get_user_state(username)
        return state.pending_request

    def approve_request(self, username: str) -> Optional[int]:
        """Approve pending request and add bonus time.

        Returns the number of minutes approved, or None if no request.
        """
        state = self.get_user_state(username)
        if not state.pending_request:
            return None

        minutes = state.pending_request.get("minutes", 15)
        self.add_bonus_time(username, minutes)
        state.pending_request = None
        self._save_state()
        log.info(f"Approved time request for {username}: {minutes} minutes")
        return minutes

    def deny_request(self, username: str) -> bool:
        """Deny and clear pending request.

        Returns True if there was a request to deny.
        """
        state = self.get_user_state(username)
        if not state.pending_request:
            return False

        state.pending_request = None
        self._save_state()
        log.info(f"Denied time request for {username}")
        return True

    def has_pending_request(self, username: str) -> bool:
        """Check if user has a pending time request."""
        state = self.get_user_state(username)
        return state.pending_request is not None


def check_login_allowed(username: str) -> tuple[bool, str]:
    """Check if a user is allowed to log in (called by PAM script).

    This reads the state file directly without needing the full agent.
    """
    if not STATE_FILE.exists():
        return True, ""  # Allow if no state

    try:
        with open(STATE_FILE) as f:
            data = json.load(f)

        user_data = data.get("users", {}).get(username, {})
        if user_data.get("blocked", False):
            reason = user_data.get("block_reason", "Access blocked")
            return False, reason

        return True, ""

    except Exception as e:
        log.error(f"PAM check failed: {e}")
        return True, ""  # Allow on error
