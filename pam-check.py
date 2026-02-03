#!/usr/bin/env python3
"""PAM check script for Kidlock.

This script is called by PAM (via pam_exec) during login to determine
if the user should be allowed to log in.

Exit codes:
  0 - Allow login
  1 - Deny login

Usage in /etc/pam.d/common-auth:
  auth required pam_exec.so /usr/local/bin/kidlock-pam-check
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

STATE_FILE = Path("/var/lib/kidlock/state.json")
CONFIG_FILE = Path("/etc/kidlock/config.yaml")


def get_user_config(username: str) -> dict | None:
    """Load user config from YAML."""
    if not CONFIG_FILE.exists():
        return None

    try:
        import yaml
        with open(CONFIG_FILE) as f:
            data = yaml.safe_load(f) or {}

        for user in data.get("users", []):
            if user.get("username") == username:
                return user
        return None
    except Exception:
        return None


def is_within_schedule(schedule: dict) -> bool:
    """Check if current time is within allowed schedule."""
    now = datetime.now()
    weekday = now.weekday()

    schedule_str = schedule.get("weekend") if weekday >= 5 else schedule.get("weekday")
    if not schedule_str:
        return True

    try:
        start_str, end_str = schedule_str.split("-")
        start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
        return start_time <= now.time() <= end_time
    except ValueError:
        return True


def check_login(username: str) -> tuple[bool, str]:
    """Check if user should be allowed to log in."""
    # Load user config
    user_config = get_user_config(username)
    if not user_config:
        return True, ""  # No config for user, allow

    # Check schedule
    schedule = user_config.get("schedule", {})
    if not is_within_schedule(schedule):
        return False, "Login not allowed at this time"

    # Load state
    if not STATE_FILE.exists():
        return True, ""

    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        return True, ""

    user_state = state.get("users", {}).get(username, {})

    # Check if explicitly blocked
    if user_state.get("blocked", False):
        reason = user_state.get("block_reason", "Access blocked")
        return False, reason

    # Check daily limit
    daily_limit = user_config.get("daily_minutes", 0)
    if daily_limit > 0:
        today = date.today().isoformat()
        if user_state.get("last_usage_date") == today:
            usage = user_state.get("usage_minutes", 0)
            if usage >= daily_limit:
                return False, "Daily time limit reached"

    return True, ""


def main():
    # Get username from PAM environment
    username = os.environ.get("PAM_USER", "")
    if not username:
        sys.exit(0)  # Allow if no user

    allowed, reason = check_login(username)

    if not allowed:
        # Print denial reason (shown to user)
        print(f"Kidlock: {reason}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
