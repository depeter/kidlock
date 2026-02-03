"""Main entry point for Kidlock agent."""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from .activity import ActivityMonitor
from .commands import CommandHandler
from .config import Config
from .dns_blocker import DnsBlocker
from .mqtt_client import MqttClient
from .platform import get_platform
from .scheduler import Scheduler

log = logging.getLogger(__name__)


class KidlockAgent:
    """Main Kidlock agent."""

    def __init__(self, config: Config):
        self.config = config
        self.platform = get_platform()
        self._running = False

        # Initialize components
        self.command_handler = CommandHandler(self.platform)
        self.dns_blocker = DnsBlocker()
        self.mqtt_client = MqttClient(config, self._on_command, self._on_settings)
        self.activity_monitor = ActivityMonitor(
            self.platform,
            config.activity.poll_interval,
            self._on_activity,
        )
        self.scheduler = Scheduler(
            self.platform,
            config.limits,
            self._on_limit_reached,
        )

    def _on_command(self, command: dict) -> None:
        """Handle incoming MQTT command."""
        self.command_handler.handle(command)

    def _on_settings(self, settings: dict) -> None:
        """Handle incoming settings update from HA."""
        self.scheduler.update_limits(settings)

        # Handle DNS blocking settings
        if "blocking_enabled" in settings:
            self.dns_blocker.set_enabled(bool(settings["blocking_enabled"]))

        if "whitelist" in settings:
            # Whitelist comes as comma-separated string from HA
            whitelist_str = settings["whitelist"]
            if isinstance(whitelist_str, str):
                domains = [d.strip() for d in whitelist_str.split(",") if d.strip()]
            else:
                domains = whitelist_str or []
            self.dns_blocker.update_whitelist(domains)

    def _on_activity(self, active_window: Optional[str], idle_seconds: int) -> None:
        """Handle activity update."""
        self.mqtt_client.publish_activity(
            active_window,
            idle_seconds,
            self.scheduler.usage_minutes,
            self.dns_blocker.enabled,
        )

    def _on_limit_reached(self, reason: str) -> None:
        """Handle limit reached event."""
        if reason == "daily_limit":
            self.platform.show_warning(
                "Time Limit Reached",
                "You have used all your screen time for today. "
                "The screen will now be locked.",
            )
        elif reason == "schedule":
            self.platform.show_warning(
                "Outside Allowed Hours",
                "Screen time is not allowed at this hour. "
                "The screen will now be locked.",
            )

        # Lock the screen after warning
        time.sleep(2)
        self.platform.lock_screen()

    def run(self) -> None:
        """Run the agent."""
        log.info(f"Starting Kidlock agent on {self.platform.name}")
        log.info(f"Hostname: {self.config.device.hostname}")

        # Connect to MQTT
        self.mqtt_client.connect()
        if not self.mqtt_client.wait_for_connection(timeout=30):
            log.error("Failed to connect to MQTT broker")
            sys.exit(1)

        # Start components
        self.activity_monitor.start()
        self.scheduler.start()

        self._running = True
        log.info("Kidlock agent running")

        # Main loop
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the agent."""
        log.info("Stopping Kidlock agent")
        self._running = False
        self.activity_monitor.stop()
        self.scheduler.stop()
        self.mqtt_client.disconnect()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Kidlock - Parental Screen Control Agent"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Load config
    try:
        config = Config.load(args.config)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)

    # Create and run agent
    agent = KidlockAgent(config)

    # Handle signals
    def signal_handler(sig, frame):
        log.info(f"Received signal {sig}")
        agent.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    agent.run()


if __name__ == "__main__":
    main()
