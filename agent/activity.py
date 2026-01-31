"""Activity monitoring for Kidlock agent."""

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .platform.base import PlatformBase

log = logging.getLogger(__name__)


class ActivityMonitor:
    """Monitors user activity and publishes updates."""

    def __init__(
        self,
        platform: "PlatformBase",
        poll_interval: int,
        on_activity: Callable[[Optional[str], int], None],
    ):
        self.platform = platform
        self.poll_interval = poll_interval
        self.on_activity = on_activity
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the activity monitor."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(f"Activity monitor started (interval={self.poll_interval}s)")

    def stop(self) -> None:
        """Stop the activity monitor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        log.info("Activity monitor stopped")

    def _run(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                active_window = self.platform.get_active_window()
                idle_seconds = self.platform.get_idle_seconds()
                self.on_activity(active_window, idle_seconds)
            except Exception as e:
                log.error(f"Activity monitor error: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(self.poll_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)
