"""Configuration handling for Kidlock agent."""

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class MqttConfig:
    broker: str = "homeassistant.local"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class DeviceConfig:
    hostname: str = field(default_factory=socket.gethostname)


@dataclass
class ActivityConfig:
    poll_interval: int = 10  # seconds


@dataclass
class ScheduleConfig:
    weekday: str = "00:00-23:59"
    weekend: str = "00:00-23:59"


@dataclass
class LimitsConfig:
    daily_minutes: int = 0  # 0 = unlimited
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)


@dataclass
class Config:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)

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

        # Activity config
        if "activity" in data:
            activity_data = data["activity"]
            config.activity = ActivityConfig(
                poll_interval=activity_data.get(
                    "poll_interval", config.activity.poll_interval
                )
            )

        # Limits config
        if "limits" in data:
            limits_data = data["limits"]
            schedule_data = limits_data.get("schedule", {})
            config.limits = LimitsConfig(
                daily_minutes=limits_data.get(
                    "daily_minutes", config.limits.daily_minutes
                ),
                schedule=ScheduleConfig(
                    weekday=schedule_data.get("weekday", "00:00-23:59"),
                    weekend=schedule_data.get("weekend", "00:00-23:59"),
                ),
            )

        return config

    @property
    def topic_prefix(self) -> str:
        """Return the MQTT topic prefix for this device."""
        return f"parental/{self.device.hostname}"
