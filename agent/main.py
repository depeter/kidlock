"""Main entry point for Kidlock agent."""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .app_tracker import AppTracker
from .config import Config
from .dns_blocker import DnsBlocker
from .enforcer import Enforcer
from .mqtt_client import MqttClient
from .notifier import Notifier
from .platform.linux import LinuxPlatform
from .tamper_detector import TamperDetector

# Directory for file-based time requests from tray
REQUEST_DIR = Path("/var/lib/kidlock/requests")

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
        self.notifier = Notifier()
        self.tamper_detector = TamperDetector()
        self.platform = LinuxPlatform()
        self.app_tracker = AppTracker()

        # Track last check time for usage accounting
        self._last_check = time.time()

        # Track user login states for event detection
        self._last_logged_in: set = set()

        # Track tamper detection state
        self._tamper_detected = False

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

        elif action == "pause":
            # Pause timer for specified user
            if username:
                self.enforcer.set_paused(username, True)
                self.notifier.send_paused_notification(username, True)
                self.mqtt_client.publish_event("pause_changed", username, {"paused": True})
            else:
                for user in self.config.users:
                    self.enforcer.set_paused(user.username, True)
                    self.notifier.send_paused_notification(user.username, True)
                    self.mqtt_client.publish_event("pause_changed", user.username, {"paused": True})

        elif action == "resume":
            # Resume timer for specified user
            if username:
                self.enforcer.set_paused(username, False)
                self.notifier.send_paused_notification(username, False)
                self.mqtt_client.publish_event("pause_changed", username, {"paused": False})
            else:
                for user in self.config.users:
                    self.enforcer.set_paused(user.username, False)
                    self.notifier.send_paused_notification(user.username, False)
                    self.mqtt_client.publish_event("pause_changed", user.username, {"paused": False})

        elif action == "add_time":
            # Add bonus time for specified user
            minutes = command.get("minutes", 15)
            if username:
                self.enforcer.add_bonus_time(username, minutes)
                self.notifier.send_bonus_time_notification(username, minutes)
                self.mqtt_client.publish_event("bonus_time", username, {"minutes": minutes})
            else:
                for user in self.config.users:
                    self.enforcer.add_bonus_time(user.username, minutes)
                    self.notifier.send_bonus_time_notification(user.username, minutes)
                    self.mqtt_client.publish_event("bonus_time", user.username, {"minutes": minutes})

        elif action == "shutdown":
            delay = command.get("delay", 0)
            try:
                subprocess.run(
                    ["shutdown", "-h", f"+{max(1, delay // 60)}"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.SubprocessError as e:
                log.error(f"Failed to schedule shutdown: {e}")

        elif action == "restart":
            delay = command.get("delay", 0)
            try:
                subprocess.run(
                    ["shutdown", "-r", f"+{max(1, delay // 60)}"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.SubprocessError as e:
                log.error(f"Failed to schedule restart: {e}")

        elif action == "cancel":
            try:
                subprocess.run(
                    ["shutdown", "-c"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.SubprocessError as e:
                log.error(f"Failed to cancel shutdown: {e}")

        elif action == "request_time":
            # Child requests more time (called via file-based IPC or MQTT)
            minutes = command.get("minutes", 15)
            reason = command.get("reason", "")
            if username:
                request = self.enforcer.create_time_request(username, minutes, reason)
                self.notifier.send_request_submitted(username)
                self.mqtt_client.publish_event("time_request", username, {
                    "request_id": request["id"],
                    "minutes": minutes,
                    "reason": reason,
                })

        elif action == "approve_request":
            # Parent approves time request
            if username:
                minutes = self.enforcer.approve_request(username)
                if minutes:
                    self.notifier.send_request_approved(username, minutes)
                    self.mqtt_client.publish_event("request_approved", username, {"minutes": minutes})
            else:
                # Approve all pending requests
                for user in self.config.users:
                    minutes = self.enforcer.approve_request(user.username)
                    if minutes:
                        self.notifier.send_request_approved(user.username, minutes)
                        self.mqtt_client.publish_event("request_approved", user.username, {"minutes": minutes})

        elif action == "deny_request":
            # Parent denies time request
            if username:
                if self.enforcer.deny_request(username):
                    self.notifier.send_request_denied(username)
                    self.mqtt_client.publish_event("request_denied", username)
            else:
                # Deny all pending requests
                for user in self.config.users:
                    if self.enforcer.deny_request(user.username):
                        self.notifier.send_request_denied(user.username)
                        self.mqtt_client.publish_event("request_denied", user.username)

        else:
            log.warning(f"Unknown command: {action}")

    def _check_file_requests(self) -> None:
        """Check for file-based time requests from tray app."""
        if not REQUEST_DIR.exists():
            return

        for request_file in REQUEST_DIR.glob("*.json"):
            try:
                with open(request_file) as f:
                    data = json.load(f)

                username = data.get("username")
                minutes = data.get("minutes", 15)
                reason = data.get("reason", "")

                # Validate user is controlled
                if username and self.config.get_user(username):
                    # Only create request if user doesn't already have one
                    if not self.enforcer.has_pending_request(username):
                        request = self.enforcer.create_time_request(username, minutes, reason)
                        self.notifier.send_request_submitted(username)
                        self.mqtt_client.publish_event("time_request", username, {
                            "request_id": request["id"],
                            "minutes": minutes,
                            "reason": reason,
                        })
                        log.info(f"Processed file request from {username}: {minutes}m")

                # Remove processed request file
                request_file.unlink()

            except Exception as e:
                log.error(f"Error processing request file {request_file}: {e}")
                # Remove invalid file
                try:
                    request_file.unlink()
                except Exception:
                    pass

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

        # Track app usage for logged-in users
        if self.config.activity.track_apps:
            for username in logged_in:
                window = self.platform.get_user_active_window(username)
                self.app_tracker.update(username, window)

        for user_config in self.config.users:
            username = user_config.username
            is_logged_in = username in logged_in
            was_logged_in = username in self._last_logged_in

            # Detect login/logout events
            if is_logged_in and not was_logged_in:
                self.mqtt_client.publish_event("login", username)
                log.info(f"User {username} logged in")
            elif not is_logged_in and was_logged_in:
                self.mqtt_client.publish_event("logout", username)
                log.info(f"User {username} logged out")

            # Check pause auto-resume
            if self.enforcer.is_paused(username):
                auto_resume_min = self.config.activity.pause_auto_resume
                if self.enforcer.check_pause_auto_resume(username, auto_resume_min):
                    self.notifier.send_paused_notification(username, False)
                    self.mqtt_client.publish_event("pause_changed", username, {"paused": False, "auto": True})

            # Check if user should be allowed
            allowed, reason = self.enforcer.check_user(user_config)

            if is_logged_in:
                if not allowed:
                    # Send final warning before logout
                    self.notifier.send_time_warning(username, 0)
                    self.mqtt_client.publish_event("time_exhausted", username)
                    # User is logged in but shouldn't be - force logout
                    self.enforcer.force_logout(username, reason)
                else:
                    # User is logged in and allowed - track usage
                    self.enforcer.unblock_user(username)  # Ensure not blocked

                    # Check for time warnings
                    self._check_and_send_warnings(user_config)

            # Publish status for each user
            self._publish_user_status(user_config, is_logged_in and allowed)

        # Update tracking for next iteration
        self._last_logged_in = logged_in.copy()

    def _check_and_send_warnings(self, user_config) -> None:
        """Check and send time warnings for a user."""
        username = user_config.username
        daily_limit = user_config.daily_minutes

        if daily_limit <= 0:
            return  # No limit, no warnings

        warnings_to_send = self.enforcer.get_warnings_to_send(
            username, daily_limit, user_config.warnings
        )

        for threshold in warnings_to_send:
            remaining = self.enforcer.get_time_remaining(username, daily_limit)
            if self.notifier.send_time_warning(username, remaining):
                self.enforcer.mark_warning_sent(username, threshold)
                self.mqtt_client.publish_event("time_warning", username, {
                    "minutes_remaining": remaining,
                    "threshold": threshold,
                })
                log.info(f"Sent {threshold}-minute warning to {username}")

    def _publish_user_status(self, user_config, is_active: bool) -> None:
        """Publish status for a user to MQTT."""
        username = user_config.username
        usage = self.enforcer.get_usage_minutes(username)
        state = self.enforcer.get_user_state(username)
        time_remaining = self.enforcer.get_time_remaining(username, user_config.daily_minutes)
        status = self.enforcer.get_status(username, user_config.daily_minutes)

        # Get app tracking data if enabled
        top_apps = None
        current_app = None
        if self.config.activity.track_apps:
            top_apps = self.app_tracker.get_top_apps(username)
            current_app = self.app_tracker.get_current_app(username)

        self.mqtt_client.publish_user_activity(
            username=username,
            active=is_active,
            usage_minutes=usage,
            blocked=state.blocked,
            block_reason=state.block_reason,
            daily_limit=user_config.daily_minutes,
            blocking_enabled=self.dns_blocker.enabled,
            time_remaining=time_remaining,
            status=status,
            paused=state.paused,
            bonus_minutes=state.bonus_minutes,
            is_idle=state.is_idle,
            top_apps=top_apps,
            current_app=current_app,
            pending_request=state.pending_request,
        )

    def _account_usage(self) -> None:
        """Account usage time for logged-in users."""
        now = time.time()
        elapsed_minutes = int((now - self._last_check) / 60)
        self._last_check = now

        if elapsed_minutes < 1:
            return

        logged_in = self.enforcer.get_logged_in_users()
        idle_threshold = self.config.activity.idle_threshold_minutes * 60  # Convert to seconds

        for user_config in self.config.users:
            username = user_config.username
            if username not in logged_in or self.enforcer.is_paused(username):
                continue

            # Check idle/locked state (only if idle detection is enabled)
            if idle_threshold > 0:
                idle_secs = self.platform.get_user_idle_seconds(username)
                is_locked = self.platform.is_session_locked(username)

                if idle_secs >= idle_threshold or is_locked:
                    self.enforcer.set_idle(username, True)
                    continue  # Don't count time when idle or locked
                else:
                    self.enforcer.set_idle(username, False)

            self.enforcer.add_usage(username, elapsed_minutes)

    def run(self) -> None:
        """Run the agent."""
        log.info("Starting Kidlock agent (system service)")
        log.info(f"Hostname: {self.config.device.hostname}")
        log.info(f"Controlling users: {[u.username for u in self.config.users]}")

        if os.geteuid() != 0:
            log.warning("Not running as root - enforcement may not work!")

        # Connect to MQTT
        self.mqtt_client.connect()
        if not self.mqtt_client.wait_for_connection(timeout=30):
            log.error("Failed to connect to MQTT broker")
            sys.exit(1)

        # Publish Home Assistant discovery
        self.mqtt_client.publish_ha_discovery(self.config.users)

        # Publish initial tamper state
        if self.config.activity.tamper_detection:
            self.mqtt_client.publish_tamper_state(False)

        # Create request directory for file-based time requests
        REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(REQUEST_DIR, 0o777)  # Allow all users to write requests

        self._running = True
        self._last_check = time.time()
        log.info("Kidlock agent running")

        # Main loop
        check_interval = self.config.activity.poll_interval
        try:
            while self._running:
                # Check for clock tampering
                if self.config.activity.tamper_detection:
                    tampered, msg = self.tamper_detector.check()
                    if tampered and not self._tamper_detected:
                        log.warning(f"Clock tamper detected: {msg}")
                        self.mqtt_client.publish_event("clock_tamper", "system", {"message": msg})
                        self.mqtt_client.publish_tamper_state(True, msg)
                        self._tamper_detected = True
                    elif not tampered and self._tamper_detected:
                        self.mqtt_client.publish_tamper_state(False)
                        self._tamper_detected = False

                self._check_and_enforce()
                self._account_usage()
                self._check_file_requests()
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
