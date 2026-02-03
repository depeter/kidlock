"""Windows platform implementation."""

import ctypes
import logging
import subprocess

from .base import PlatformBase

log = logging.getLogger(__name__)


class WindowsPlatform(PlatformBase):
    """Windows-specific implementations using Win32 API."""

    @property
    def name(self) -> str:
        return "windows"

    def lock_screen(self) -> bool:
        """Lock screen using LockWorkStation."""
        try:
            result = ctypes.windll.user32.LockWorkStation()
            if result:
                log.info("Screen locked")
                return True
        except Exception as e:
            log.error(f"Lock screen failed: {e}")
        return False

    def unlock_screen(self) -> bool:
        """Unlock screen - not possible on Windows without credentials."""
        log.warning("Screen unlock not supported on Windows")
        return False

    def shutdown(self, delay: int = 0) -> bool:
        """Shutdown using shutdown command."""
        try:
            result = subprocess.run(
                ["shutdown", "/s", "/t", str(delay)],
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
        """Restart using shutdown command."""
        try:
            result = subprocess.run(
                ["shutdown", "/r", "/t", str(delay)],
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
                ["shutdown", "/a"],
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
        """Get active window title using Win32 API."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value or None
        except Exception as e:
            log.debug(f"Failed to get active window: {e}")
        return None

    def get_idle_seconds(self) -> int:
        """Get idle time using GetLastInputInfo."""
        try:
            # LASTINPUTINFO structure
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("dwTime", ctypes.c_uint),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                # GetTickCount returns milliseconds since system start
                tick_count = ctypes.windll.kernel32.GetTickCount()
                idle_ms = tick_count - lii.dwTime
                return idle_ms // 1000
        except Exception as e:
            log.debug(f"Failed to get idle time: {e}")
        return 0

    def show_warning(self, title: str, message: str) -> None:
        """Show warning popup using MessageBox."""
        try:
            # MB_OK | MB_ICONWARNING | MB_TOPMOST
            MB_OK = 0x0
            MB_ICONWARNING = 0x30
            MB_TOPMOST = 0x40000

            ctypes.windll.user32.MessageBoxW(
                None, message, title, MB_OK | MB_ICONWARNING | MB_TOPMOST
            )
            log.info(f"Warning shown: {title}")
        except Exception as e:
            log.error(f"Failed to show warning: {e}")
