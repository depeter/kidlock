"""Time tracking and schedule enforcement for Kidlock agent."""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import LimitsConfig
    from .platform.base import PlatformBase

log = logging.getLogger(__name__)


class Scheduler:
    """Tracks usage time and enforces schedule limits."""

    def __init__(
        self,
        platform: "PlatformBase",
        limits: "LimitsConfig",
        on_limit_reached: Callable[[str], None],
    ):
        self.platform = platform
        self.limits = limits
        self.on_limit_reached = on_limit_reached

        self._running = False
        self._thread: threading.Thread | None = None
        self._usage_minutes = 0
        self._last_reset_date: str | None = None
        self._state_file = self._get_state_file()
        self._locked_for_schedule = False

        self._load_state()

    def _get_state_file(self) -> Path:
        """Get path to state file."""
        if os.name == "nt":
            # Windows: use AppData
            base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
            state_dir = base / "kidlock"
        else:
            # Linux: use XDG_STATE_HOME or fallback
            xdg_state = os.environ.get("XDG_STATE_HOME")
            if xdg_state:
                state_dir = Path(xdg_state) / "kidlock"
            else:
                state_dir = Path.home() / ".local" / "state" / "kidlock"

        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "usage.json"

    def _load_state(self) -> None:
        """Load usage state from file."""
        try:
            if self._state_file.exists():
                with open(self._state_file) as f:
                    data = json.load(f)
                    self._last_reset_date = data.get("date")
                    self._usage_minutes = data.get("minutes", 0)

                    # Reset if it's a new day
                    today = datetime.now().strftime("%Y-%m-%d")
                    if self._last_reset_date != today:
                        log.info("New day, resetting usage counter")
                        self._usage_minutes = 0
                        self._last_reset_date = today
        except Exception as e:
            log.error(f"Failed to load state: {e}")

    def _save_state(self) -> None:
        """Save usage state to file."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            with open(self._state_file, "w") as f:
                json.dump({
                    "date": today,
                    "minutes": self._usage_minutes,
                }, f)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    @property
    def usage_minutes(self) -> int:
        """Get current usage minutes."""
        return self._usage_minutes

    def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._save_state()
        log.info("Scheduler stopped")

    def _run(self) -> None:
        """Main scheduler loop."""
        last_minute = datetime.now().minute

        while self._running:
            now = datetime.now()

            # Increment usage every minute (if not idle)
            if now.minute != last_minute:
                last_minute = now.minute
                idle = self.platform.get_idle_seconds()

                # Only count if user was active in the last minute
                if idle < 60:
                    self._usage_minutes += 1
                    self._save_state()
                    log.debug(f"Usage: {self._usage_minutes} minutes")

                # Check daily limit
                if self.limits.daily_minutes > 0:
                    if self._usage_minutes >= self.limits.daily_minutes:
                        log.warning("Daily limit reached!")
                        self.on_limit_reached("daily_limit")

            # Check schedule
            if not self._is_within_schedule():
                if not self._locked_for_schedule:
                    log.warning("Outside allowed hours!")
                    self._locked_for_schedule = True
                    self.on_limit_reached("schedule")
            else:
                self._locked_for_schedule = False

            time.sleep(10)  # Check every 10 seconds

    def _is_within_schedule(self) -> bool:
        """Check if current time is within allowed schedule."""
        now = datetime.now()
        is_weekend = now.weekday() >= 5  # Saturday = 5, Sunday = 6

        schedule_str = (
            self.limits.schedule.weekend if is_weekend
            else self.limits.schedule.weekday
        )

        try:
            start_str, end_str = schedule_str.split("-")
            start_time = self._parse_time(start_str)
            end_time = self._parse_time(end_str)

            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_time[0] * 60 + start_time[1]
            end_minutes = end_time[0] * 60 + end_time[1]

            return start_minutes <= current_minutes <= end_minutes
        except Exception as e:
            log.error(f"Failed to parse schedule: {e}")
            return True  # Allow if schedule is invalid

    def _parse_time(self, time_str: str) -> tuple[int, int]:
        """Parse time string like '15:00' to (hour, minute)."""
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1])

    def update_limits(self, settings: dict) -> None:
        """Update limits from HA settings.

        Args:
            settings: Dict with keys:
                - daily_minutes: int
                - weekday_start: str (HH:MM)
                - weekday_end: str (HH:MM)
                - weekend_start: str (HH:MM)
                - weekend_end: str (HH:MM)
        """
        if "daily_minutes" in settings:
            old_limit = self.limits.daily_minutes
            self.limits.daily_minutes = int(settings["daily_minutes"])
            log.info(f"Daily limit updated: {old_limit} -> {self.limits.daily_minutes} minutes")

        # Build schedule strings from start/end times
        weekday_start = settings.get("weekday_start")
        weekday_end = settings.get("weekday_end")
        if weekday_start and weekday_end:
            old_weekday = self.limits.schedule.weekday
            self.limits.schedule.weekday = f"{weekday_start}-{weekday_end}"
            log.info(f"Weekday schedule updated: {old_weekday} -> {self.limits.schedule.weekday}")

        weekend_start = settings.get("weekend_start")
        weekend_end = settings.get("weekend_end")
        if weekend_start and weekend_end:
            old_weekend = self.limits.schedule.weekend
            self.limits.schedule.weekend = f"{weekend_start}-{weekend_end}"
            log.info(f"Weekend schedule updated: {old_weekend} -> {self.limits.schedule.weekend}")
