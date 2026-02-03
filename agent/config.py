"""Configuration handling for Kidlock agent."""

import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MqttConfig:
    broker: str = "homeassistant.local"
    port: int = 1883
    username: str | None = None
    password: str | None = None


@dataclass
class DeviceConfig:
    hostname: str = field(default_factory=socket.gethostname)


@dataclass
class ScheduleConfig:
    weekday: str = "00:00-23:59"
    weekend: str = "00:00-23:59"


@dataclass
class UserConfig:
    """Configuration for a controlled user."""
    username: str
    daily_minutes: int = 0  # 0 = unlimited
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    warnings: list[int] = field(default_factory=lambda: [10, 5, 1])  # Minutes before limit to warn


@dataclass
class ActivityConfig:
    poll_interval: int = 10  # seconds
    pause_auto_resume: int = 30  # Minutes before auto-resuming a paused timer
    tamper_detection: bool = True  # Detect system clock manipulation
    idle_threshold_minutes: int = 5  # Don't count time when idle > this (0 = disabled)
    track_apps: bool = True  # Track active application usage


@dataclass
class Config:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    users: list[UserConfig] = field(default_factory=list)
    activity: ActivityConfig = field(default_factory=ActivityConfig)

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Load configuration from YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        config = cls()

        # MQTT config
        if "mqtt" in data:
            mqtt_data = data["mqtt"]
            config.mqtt = MqttConfig(
                broker=mqtt_data.get("broker", config.mqtt.broker),
                port=mqtt_data.get("port", config.mqtt.port),
                username=mqtt_data.get("username"),
                password=mqtt_data.get("password"),
            )

        # Device config
        if "device" in data:
            device_data = data["device"]
            config.device = DeviceConfig(
                hostname=device_data.get("hostname", socket.gethostname())
            )

        # Users config
        if "users" in data:
            for user_data in data["users"]:
                schedule_data = user_data.get("schedule", {})
                user = UserConfig(
                    username=user_data["username"],
                    daily_minutes=user_data.get("daily_minutes", 0),
                    schedule=ScheduleConfig(
                        weekday=schedule_data.get("weekday", "00:00-23:59"),
                        weekend=schedule_data.get("weekend", "00:00-23:59"),
                    ),
                    warnings=user_data.get("warnings", [10, 5, 1]),
                )
                config.users.append(user)

        # Activity config
        if "activity" in data:
            activity_data = data["activity"]
            config.activity = ActivityConfig(
                poll_interval=activity_data.get(
                    "poll_interval", config.activity.poll_interval
                ),
                pause_auto_resume=activity_data.get(
                    "pause_auto_resume", config.activity.pause_auto_resume
                ),
                tamper_detection=activity_data.get(
                    "tamper_detection", config.activity.tamper_detection
                ),
                idle_threshold_minutes=activity_data.get(
                    "idle_threshold_minutes", config.activity.idle_threshold_minutes
                ),
                track_apps=activity_data.get(
                    "track_apps", config.activity.track_apps
                ),
            )

        return config

    def get_user(self, username: str) -> UserConfig | None:
        """Get config for a specific user."""
        for user in self.users:
            if user.username == username:
                return user
        return None

    @property
    def topic_prefix(self) -> str:
        """Return the MQTT topic prefix for this device."""
        return f"parental/{self.device.hostname}"
