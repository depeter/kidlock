"""Clock tamper detection for Kidlock agent."""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

log = logging.getLogger(__name__)


class TamperDetector:
    """Detects system clock manipulation by comparing wall clock to monotonic time."""

    def __init__(self, threshold_seconds: int = 60):
        """Initialize the tamper detector.

        Args:
            threshold_seconds: Minimum backward clock jump to trigger alarm (default 60s)
        """
        self._last_wall_time: Optional[datetime] = None
        self._last_monotonic: Optional[float] = None
        self._threshold = threshold_seconds

    def check(self) -> Tuple[bool, str]:
        """Check for clock tampering using monotonic time comparison.

        Returns:
            Tuple of (tampered, message).
            tampered is True if wall clock jumped backwards by more than threshold.
        """
        now = datetime.now()
        now_mono = time.monotonic()

        if self._last_wall_time is None:
            self._last_wall_time = now
            self._last_monotonic = now_mono
            return False, "Initial check"

        # Calculate expected wall time based on monotonic elapsed time
        mono_elapsed = now_mono - self._last_monotonic
        expected = self._last_wall_time + timedelta(seconds=mono_elapsed)
        diff = (now - expected).total_seconds()

        # Update state
        self._last_wall_time = now
        self._last_monotonic = now_mono

        if diff < -self._threshold:
            # Clock went backwards by more than threshold
            jump_seconds = int(abs(diff))
            log.warning(f"Clock tamper detected: jumped backwards by {jump_seconds} seconds")
            return True, f"Clock jumped backwards by {jump_seconds} seconds"

        return False, "OK"

    def reset(self) -> None:
        """Reset the detector state."""
        self._last_wall_time = None
        self._last_monotonic = None
