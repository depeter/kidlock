"""Application usage tracking for Kidlock agent."""

import logging
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class AppTracker:
    """Tracks application usage by monitoring active window titles."""

    def __init__(self):
        # Current window per user
        self._current_windows: Dict[str, str] = {}
        # When current window started
        self._current_start: Dict[str, datetime] = {}
        # Daily usage per user: {username: {app_name: seconds}}
        self._daily_usage: Dict[str, Dict[str, int]] = {}
        # Track which date the usage is for
        self._usage_date: Optional[str] = None

    def _reset_if_new_day(self) -> None:
        """Reset daily usage if it's a new day."""
        today = date.today().isoformat()
        if self._usage_date != today:
            self._daily_usage.clear()
            self._current_windows.clear()
            self._current_start.clear()
            self._usage_date = today
            log.debug("App tracker reset for new day")

    def _extract_app_name(self, window_title: str) -> str:
        """Extract app name from window title.

        Tries to extract the application name from common window title formats:
        - "Document - Application" -> "Application"
        - "Application: Document" -> "Application"
        - "Application" -> "Application"
        """
        if not window_title:
            return "Unknown"

        # Common browser patterns
        browser_patterns = [
            (r".* [-\u2014] (Mozilla Firefox|Firefox)$", "Firefox"),
            (r".* [-\u2014] (Google Chrome|Chromium)$", "Chrome"),
            (r".* [-\u2014] (Brave)$", "Brave"),
            (r".* [-\u2014] (Microsoft Edge)$", "Edge"),
        ]

        for pattern, name in browser_patterns:
            if re.match(pattern, window_title, re.IGNORECASE):
                return name

        # Common patterns: "Title - Application"
        if " - " in window_title:
            parts = window_title.rsplit(" - ", 1)
            if len(parts) == 2 and parts[1]:
                return parts[1].strip()

        # Pattern: "Title \u2014 Application" (em-dash)
        if " \u2014 " in window_title:
            parts = window_title.rsplit(" \u2014 ", 1)
            if len(parts) == 2 and parts[1]:
                return parts[1].strip()

        # Pattern: "Application: Title"
        if ": " in window_title:
            parts = window_title.split(": ", 1)
            if len(parts) == 2 and parts[0]:
                return parts[0].strip()

        # Fallback: use the whole title, truncated
        return window_title[:50] if len(window_title) > 50 else window_title

    def update(self, username: str, window_title: Optional[str]) -> None:
        """Track window change and accumulate time for previous window.

        Args:
            username: The user whose window changed
            window_title: The new active window title (or None if no window)
        """
        self._reset_if_new_day()

        now = datetime.now()
        current_window = self._current_windows.get(username)
        current_start = self._current_start.get(username)

        # If window changed, accumulate time for previous window
        if current_window and current_start and current_window != window_title:
            elapsed = (now - current_start).total_seconds()
            if elapsed > 0:
                app_name = self._extract_app_name(current_window)
                if username not in self._daily_usage:
                    self._daily_usage[username] = {}
                self._daily_usage[username][app_name] = (
                    self._daily_usage[username].get(app_name, 0) + int(elapsed)
                )
                log.debug(f"User {username}: {app_name} +{int(elapsed)}s")

        # Update current tracking
        if window_title:
            if window_title != current_window:
                self._current_windows[username] = window_title
                self._current_start[username] = now
        else:
            # No active window
            self._current_windows.pop(username, None)
            self._current_start.pop(username, None)

    def get_top_apps(self, username: str, limit: int = 5) -> List[Tuple[str, int]]:
        """Return top apps by usage time for a user.

        Args:
            username: The user to get stats for
            limit: Maximum number of apps to return

        Returns:
            List of (app_name, seconds) tuples, sorted by time descending
        """
        self._reset_if_new_day()

        if username not in self._daily_usage:
            return []

        usage = self._daily_usage[username]
        sorted_apps = sorted(usage.items(), key=lambda x: x[1], reverse=True)
        return sorted_apps[:limit]

    def get_current_app(self, username: str) -> Optional[str]:
        """Get the currently active app for a user."""
        window = self._current_windows.get(username)
        if window:
            return self._extract_app_name(window)
        return None

    def get_total_tracked_seconds(self, username: str) -> int:
        """Get total tracked time for a user today."""
        self._reset_if_new_day()

        if username not in self._daily_usage:
            return 0

        return sum(self._daily_usage[username].values())
