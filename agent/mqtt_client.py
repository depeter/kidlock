"""MQTT client for Kidlock agent."""

import json
import logging
import threading
from typing import Callable, List, Optional

import paho.mqtt.client as mqtt

from .config import Config, UserConfig

log = logging.getLogger(__name__)

# Home Assistant MQTT Discovery prefix
HA_DISCOVERY_PREFIX = "homeassistant"


class MqttClient:
    """MQTT client with LWT and command subscription."""

    def __init__(
        self,
        config: Config,
        on_command: Callable[[dict], None],
        on_settings: Optional[Callable[[dict], None]] = None,
    ):
        self.config = config
        self.on_command = on_command
        self.on_settings = on_settings
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()

    @property
    def topic_status(self) -> str:
        return f"{self.config.topic_prefix}/status"

    @property
    def topic_activity(self) -> str:
        return f"{self.config.topic_prefix}/activity"

    @property
    def topic_command(self) -> str:
        return f"{self.config.topic_prefix}/command"

    @property
    def topic_settings(self) -> str:
        return f"{self.config.topic_prefix}/settings"

    def connect(self) -> None:
        """Connect to MQTT broker."""
        # paho-mqtt 2.x uses CallbackAPIVersion
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=f"kidlock-{self.config.device.hostname}",
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            # paho-mqtt 1.x fallback
            self._client = mqtt.Client(
                client_id=f"kidlock-{self.config.device.hostname}",
                protocol=mqtt.MQTTv311,
            )

        # Set credentials if provided
        if self.config.mqtt.username:
            self._client.username_pw_set(
                self.config.mqtt.username,
                self.config.mqtt.password,
            )

        # Set Last Will Testament for offline detection
        lwt_payload = json.dumps({"state": "offline"})
        self._client.will_set(
            self.topic_status,
            payload=lwt_payload,
            qos=1,
            retain=True,
        )

        # Set callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        log.info(f"Connecting to {self.config.mqtt.broker}:{self.config.mqtt.port}")
        self._client.connect(
            self.config.mqtt.broker,
            self.config.mqtt.port,
            keepalive=60,
        )
        self._client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            # Publish offline status before disconnecting
            self.publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()
            log.info("Disconnected from MQTT broker")

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for connection to be established."""
        return self._connected.wait(timeout)

    def publish_status(self, state: str) -> None:
        """Publish device status."""
        if self._client:
            payload = json.dumps({"state": state})
            self._client.publish(self.topic_status, payload, qos=1, retain=True)
            log.debug(f"Published status: {state}")

    def publish_ha_discovery(self, users: List[UserConfig]) -> None:
        """Publish Home Assistant MQTT discovery messages."""
        if not self._client:
            return

        hostname = self.config.device.hostname
        device_info = {
            "identifiers": [f"kidlock_{hostname}"],
            "name": f"Kidlock {hostname}",
            "manufacturer": "Kidlock",
            "model": "Parental Control Agent",
        }

        # Device online binary sensor
        self._publish_discovery("binary_sensor", f"{hostname}_online", {
            "name": f"{hostname} Online",
            "unique_id": f"kidlock_{hostname}_online",
            "device": device_info,
            "state_topic": self.topic_status,
            "value_template": "{{ value_json.state }}",
            "payload_on": "online",
            "payload_off": "offline",
            "device_class": "connectivity",
        })

        # Per-user entities
        for user in users:
            username = user.username
            user_topic = f"{self.config.topic_prefix}/user/{username}"
            user_id = f"{hostname}_{username}"

            # User active binary sensor
            self._publish_discovery("binary_sensor", f"{user_id}_active", {
                "name": f"{username} Active",
                "unique_id": f"kidlock_{user_id}_active",
                "device": device_info,
                "state_topic": user_topic,
                "value_template": "{{ 'ON' if value_json.active else 'OFF' }}",
                "device_class": "presence",
            })

            # User blocked binary sensor
            self._publish_discovery("binary_sensor", f"{user_id}_blocked", {
                "name": f"{username} Blocked",
                "unique_id": f"kidlock_{user_id}_blocked",
                "device": device_info,
                "state_topic": user_topic,
                "value_template": "{{ 'ON' if value_json.blocked else 'OFF' }}",
                "icon": "mdi:account-lock",
            })

            # Usage sensor
            self._publish_discovery("sensor", f"{user_id}_usage", {
                "name": f"{username} Usage",
                "unique_id": f"kidlock_{user_id}_usage",
                "device": device_info,
                "state_topic": user_topic,
                "value_template": "{{ value_json.usage_minutes }}",
                "unit_of_measurement": "min",
                "icon": "mdi:clock-outline",
            })

            # Daily limit sensor
            self._publish_discovery("sensor", f"{user_id}_limit", {
                "name": f"{username} Daily Limit",
                "unique_id": f"kidlock_{user_id}_limit",
                "device": device_info,
                "state_topic": user_topic,
                "value_template": "{{ value_json.daily_limit }}",
                "unit_of_measurement": "min",
                "icon": "mdi:timer-sand",
            })

            # Lock button
            self._publish_discovery("button", f"{user_id}_lock", {
                "name": f"{username} Lock",
                "unique_id": f"kidlock_{user_id}_lock",
                "device": device_info,
                "command_topic": self.topic_command,
                "payload_press": json.dumps({"action": "lock", "user": username}),
                "icon": "mdi:lock",
            })

            # Unlock button
            self._publish_discovery("button", f"{user_id}_unlock", {
                "name": f"{username} Unlock",
                "unique_id": f"kidlock_{user_id}_unlock",
                "device": device_info,
                "command_topic": self.topic_command,
                "payload_press": json.dumps({"action": "unlock", "user": username}),
                "icon": "mdi:lock-open",
            })

        log.info(f"Published HA discovery for {len(users)} users")

    def _publish_discovery(self, component: str, object_id: str, config: dict) -> None:
        """Publish a single HA discovery message."""
        topic = f"{HA_DISCOVERY_PREFIX}/{component}/kidlock/{object_id}/config"
        self._client.publish(topic, json.dumps(config), qos=1, retain=True)

    def publish_activity(
        self,
        active_window: Optional[str],
        idle_seconds: int,
        usage_minutes: int = 0,
        blocking_enabled: bool = False,
    ) -> None:
        """Publish activity data (legacy single-user mode)."""
        if self._client:
            payload = json.dumps({
                "active_window": active_window or "",
                "idle_seconds": idle_seconds,
                "usage_minutes": usage_minutes,
                "blocking_enabled": blocking_enabled,
            })
            self._client.publish(self.topic_activity, payload, qos=0, retain=False)
            log.debug(f"Published activity: window={active_window}, idle={idle_seconds}s, blocking={blocking_enabled}")

    def publish_user_activity(
        self,
        username: str,
        active: bool,
        usage_minutes: int,
        blocked: bool,
        block_reason: str,
        daily_limit: int,
        blocking_enabled: bool = False,
    ) -> None:
        """Publish per-user activity data."""
        if self._client:
            topic = f"{self.config.topic_prefix}/user/{username}"
            payload = json.dumps({
                "username": username,
                "active": active,
                "usage_minutes": usage_minutes,
                "daily_limit": daily_limit,
                "blocked": blocked,
                "block_reason": block_reason,
                "blocking_enabled": blocking_enabled,
            })
            self._client.publish(topic, payload, qos=0, retain=True)
            log.debug(f"Published user activity: {username} active={active} usage={usage_minutes}m")

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        rc: int,
    ) -> None:
        """Handle connection established."""
        if rc == 0:
            log.info("Connected to MQTT broker")
            self._connected.set()

            # Subscribe to command topic
            client.subscribe(self.topic_command, qos=1)
            log.info(f"Subscribed to {self.topic_command}")

            # Subscribe to settings topic
            client.subscribe(self.topic_settings, qos=1)
            log.info(f"Subscribed to {self.topic_settings}")

            # Publish online status
            self.publish_status("online")
        else:
            log.error(f"Connection failed with code {rc}")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        rc: int,
    ) -> None:
        """Handle disconnection."""
        self._connected.clear()
        if rc != 0:
            log.warning(f"Unexpected disconnect (rc={rc}), will reconnect")
        else:
            log.info("Disconnected cleanly")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Handle incoming message."""
        try:
            payload = json.loads(msg.payload.decode())

            if msg.topic == self.topic_settings:
                log.info(f"Received settings: {payload}")
                if self.on_settings:
                    self.on_settings(payload)
            elif msg.topic == self.topic_command:
                log.info(f"Received command: {payload}")
                self.on_command(payload)
            else:
                log.warning(f"Unknown topic: {msg.topic}")
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON in message: {e}")
        except Exception as e:
            log.error(f"Error handling message: {e}")
