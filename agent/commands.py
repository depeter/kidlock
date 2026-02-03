"""Command dispatcher for Kidlock agent."""

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .platform.base import PlatformBase

log = logging.getLogger(__name__)


class CommandHandler:
    """Handles commands received via MQTT."""

    def __init__(self, platform: "PlatformBase"):
        self.platform = platform
        self._shutdown_timer: threading.Timer | None = None

    def handle(self, command: dict) -> None:
        """Dispatch a command."""
        action = command.get("action", "").lower()

        handlers = {
            "lock": self._handle_lock,
            "unlock": self._handle_unlock,
            "shutdown": self._handle_shutdown,
            "restart": self._handle_restart,
            "cancel": self._handle_cancel,
        }

        handler = handlers.get(action)
        if handler:
            handler(command)
        else:
            log.warning(f"Unknown action: {action}")

    def _handle_lock(self, command: dict) -> None:
        """Handle lock command."""
        log.info("Executing lock command")
        self.platform.lock_screen()

    def _handle_unlock(self, command: dict) -> None:
        """Handle unlock command."""
        log.info("Executing unlock command")
        self.platform.unlock_screen()

    def _handle_shutdown(self, command: dict) -> None:
        """Handle shutdown command with optional delay and warning."""
        delay = command.get("delay", 0)
        warning = command.get("warning", False)

        log.info(f"Executing shutdown (delay={delay}s, warning={warning})")

        if warning and delay > 0:
            self._show_warning_and_execute(
                f"Shutdown in {delay} seconds",
                "This computer will shut down soon. Save your work!",
                delay,
                self.platform.shutdown,
            )
        elif delay > 0:
            self.platform.shutdown(delay)
        else:
            self.platform.shutdown()

    def _handle_restart(self, command: dict) -> None:
        """Handle restart command with optional delay and warning."""
        delay = command.get("delay", 0)
        warning = command.get("warning", False)

        log.info(f"Executing restart (delay={delay}s, warning={warning})")

        if warning and delay > 0:
            self._show_warning_and_execute(
                f"Restart in {delay} seconds",
                "This computer will restart soon. Save your work!",
                delay,
                self.platform.restart,
            )
        elif delay > 0:
            self.platform.restart(delay)
        else:
            self.platform.restart()

    def _handle_cancel(self, command: dict) -> None:
        """Handle cancel command."""
        log.info("Executing cancel command")
        if self._shutdown_timer:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None
        self.platform.cancel_shutdown()

    def _show_warning_and_execute(
        self,
        title: str,
        message: str,
        delay: int,
        action_func,
    ) -> None:
        """Show warning popup then execute action after delay."""
        # Show warning immediately
        self.platform.show_warning(title, message)

        # Cancel any existing timer
        if self._shutdown_timer:
            self._shutdown_timer.cancel()

        # Schedule action
        def execute():
            action_func(0)  # Execute with no additional delay

        self._shutdown_timer = threading.Timer(delay, execute)
        self._shutdown_timer.start()
