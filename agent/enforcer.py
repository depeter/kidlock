"""User session enforcement for Kidlock agent."""

import json
import logging
import os
import subprocess
from datetime import date, datetime, time
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

    def to_dict(self) -> dict:
        return {
            "usage_minutes": self.usage_minutes,
            "last_usage_date": self.last_usage_date,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }

    @classmethod
    def from_dict(cls, username: str, data: dict) -> "UserState":
        state = cls(username)
        state.usage_minutes = data.get("usage_minutes", 0)
        state.last_usage_date = data.get("last_usage_date")
        state.blocked = data.get("blocked", False)
        state.block_reason = data.get("block_reason", "")
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

        # Reset usage if new day
        if state.last_usage_date != today:
            state.usage_minutes = 0
            state.last_usage_date = today
            self._save_state()

        # Check schedule
        if not self.is_within_schedule(user_config.schedule):
            return False, "Outside allowed hours"

        # Check daily limit
        if user_config.daily_minutes > 0:
            if state.usage_minutes >= user_config.daily_minutes:
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
