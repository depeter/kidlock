"""Main entry point for Kidlock agent."""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from .config import Config
from .dns_blocker import DnsBlocker
from .enforcer import Enforcer
from .mqtt_client import MqttClient

log = logging.getLogger(__name__)

# Default config paths
SYSTEM_CONFIG = Path("/etc/kidlock/config.yaml")
USER_CONFIG = Path.home() / ".config/kidlock/config.yaml"


class KidlockAgent:
    """Main Kidlock agent - runs as root system service."""

    def __init__(self, config: Config):
        self.config = config
        self._running = False

        # Initialize components
        self.enforcer = Enforcer()
        self.dns_blocker = DnsBlocker()
        self.mqtt_client = MqttClient(config, self._on_command, self._on_settings)

        # Track last check time for usage accounting
        self._last_check = time.time()

    def _on_command(self, command: dict) -> None:
        """Handle incoming MQTT command."""
        action = command.get("action", "").lower()
        username = command.get("user")  # Optional: target specific user

        if action == "lock":
            # Force logout specified user or all controlled users
            if username:
                user_config = self.config.get_user(username)
                if user_config:
                    self.enforcer.force_logout(username, "Remote lock command")
            else:
                for user in self.config.users:
                    self.enforcer.force_logout(user.username, "Remote lock command")

        elif action == "unlock":
            # Unblock specified user or all controlled users
            if username:
                self.enforcer.unblock_user(username)
            else:
                for user in self.config.users:
                    self.enforcer.unblock_user(user.username)

        elif action == "shutdown":
            delay = command.get("delay", 0)
            os.system(f"shutdown -h +{max(1, delay // 60)}")

        elif action == "restart":
            delay = command.get("delay", 0)
            os.system(f"shutdown -r +{max(1, delay // 60)}")

        elif action == "cancel":
            os.system("shutdown -c")

        else:
            log.warning(f"Unknown command: {action}")

    def _on_settings(self, settings: dict) -> None:
        """Handle incoming settings update from HA."""
        # Handle DNS blocking settings
        if "blocking_enabled" in settings:
            self.dns_blocker.set_enabled(bool(settings["blocking_enabled"]))

        if "whitelist" in settings:
            whitelist_str = settings["whitelist"]
            if isinstance(whitelist_str, str):
                domains = [d.strip() for d in whitelist_str.split(",") if d.strip()]
            else:
                domains = whitelist_str or []
            self.dns_blocker.update_whitelist(domains)

        # TODO: Handle per-user settings updates

    def _check_and_enforce(self) -> None:
        """Check all controlled users and enforce rules."""
        logged_in = self.enforcer.get_logged_in_users()

        for user_config in self.config.users:
            username = user_config.username
            is_logged_in = username in logged_in

            # Check if user should be allowed
            allowed, reason = self.enforcer.check_user(user_config)

            if is_logged_in:
                if not allowed:
                    # User is logged in but shouldn't be - force logout
                    self.enforcer.force_logout(username, reason)
                else:
                    # User is logged in and allowed - track usage
                    self.enforcer.unblock_user(username)  # Ensure not blocked

            # Publish status for each user
            self._publish_user_status(user_config, is_logged_in and allowed)

    def _publish_user_status(self, user_config, is_active: bool) -> None:
        """Publish status for a user to MQTT."""
        username = user_config.username
        usage = self.enforcer.get_usage_minutes(username)
        state = self.enforcer.get_user_state(username)

        self.mqtt_client.publish_user_activity(
            username=username,
            active=is_active,
            usage_minutes=usage,
            blocked=state.blocked,
            block_reason=state.block_reason,
            daily_limit=user_config.daily_minutes,
            blocking_enabled=self.dns_blocker.enabled,
        )

    def _account_usage(self) -> None:
        """Account usage time for logged-in users."""
        now = time.time()
        elapsed_minutes = int((now - self._last_check) / 60)
        self._last_check = now

        if elapsed_minutes < 1:
            return

        logged_in = self.enforcer.get_logged_in_users()

        for user_config in self.config.users:
            if user_config.username in logged_in:
                self.enforcer.add_usage(user_config.username, elapsed_minutes)

    def run(self) -> None:
        """Run the agent."""
        log.info(f"Starting Kidlock agent (system service)")
        log.info(f"Hostname: {self.config.device.hostname}")
        log.info(f"Controlling users: {[u.username for u in self.config.users]}")

        if os.geteuid() != 0:
            log.warning("Not running as root - enforcement may not work!")

        # Connect to MQTT
        self.mqtt_client.connect()
        if not self.mqtt_client.wait_for_connection(timeout=30):
            log.error("Failed to connect to MQTT broker")
            sys.exit(1)

        self._running = True
        self._last_check = time.time()
        log.info("Kidlock agent running")

        # Main loop
        check_interval = self.config.activity.poll_interval
        try:
            while self._running:
                self._check_and_enforce()
                self._account_usage()
                time.sleep(check_interval)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the agent."""
        log.info("Stopping Kidlock agent")
        self._running = False
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
        description="Kidlock - Parental Control Agent (System Service)"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        help=f"Path to config file (default: {SYSTEM_CONFIG} or {USER_CONFIG})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Find config file
    if args.config:
        config_path = args.config
    elif SYSTEM_CONFIG.exists():
        config_path = SYSTEM_CONFIG
    elif USER_CONFIG.exists():
        config_path = USER_CONFIG
    else:
        log.error(f"No config file found at {SYSTEM_CONFIG} or {USER_CONFIG}")
        sys.exit(1)

    # Load config
    try:
        config = Config.load(config_path)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)

    if not config.users:
        log.error("No users configured - add 'users:' section to config")
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
