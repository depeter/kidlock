"""Tests for config module."""

import tempfile
from pathlib import Path

import pytest

from agent.config import Config, MqttConfig, ScheduleConfig, UserConfig


class TestConfig:
    """Tests for Config class."""

    def test_load_valid_config(self, temp_config_file):
        """Test loading a valid config file."""
        config = Config.load(temp_config_file)

        assert config.mqtt.broker == "localhost"
        assert config.mqtt.port == 1883
        assert config.mqtt.username == "test"
        assert len(config.users) == 1
        assert config.users[0].username == "testuser"
        assert config.users[0].daily_minutes == 120

    def test_load_missing_file(self):
        """Test loading a non-existent config file."""
        with pytest.raises(FileNotFoundError):
            Config.load(Path("/nonexistent/config.yaml"))

    def test_load_empty_file(self):
        """Test loading an empty config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            config = Config.load(Path(f.name))

        # Should use defaults
        assert config.mqtt.broker == "homeassistant.local"
        assert config.users == []

    def test_load_partial_config(self):
        """Test loading a config with only some fields."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("mqtt:\n  broker: custom.local\n")
            f.flush()
            config = Config.load(Path(f.name))

        assert config.mqtt.broker == "custom.local"
        assert config.mqtt.port == 1883  # Default

    def test_get_user_exists(self, temp_config_file):
        """Test getting an existing user."""
        config = Config.load(temp_config_file)
        user = config.get_user("testuser")

        assert user is not None
        assert user.username == "testuser"

    def test_get_user_not_exists(self, temp_config_file):
        """Test getting a non-existent user."""
        config = Config.load(temp_config_file)
        user = config.get_user("nobody")

        assert user is None

    def test_topic_prefix(self, temp_config_file):
        """Test topic prefix generation."""
        config = Config.load(temp_config_file)
        # Topic prefix uses hostname
        assert config.topic_prefix.startswith("parental/")


class TestScheduleConfig:
    """Tests for ScheduleConfig defaults."""

    def test_default_schedule(self):
        """Test default schedule allows all day."""
        schedule = ScheduleConfig()
        assert schedule.weekday == "00:00-23:59"
        assert schedule.weekend == "00:00-23:59"


class TestUserConfig:
    """Tests for UserConfig defaults."""

    def test_default_user_config(self):
        """Test default user config values."""
        user = UserConfig(username="test")
        assert user.daily_minutes == 0  # Unlimited
        assert user.warnings == [10, 5, 1]

    def test_user_config_with_values(self):
        """Test user config with custom values."""
        user = UserConfig(
            username="kid",
            daily_minutes=180,
            warnings=[15, 10, 5, 1],
        )
        assert user.username == "kid"
        assert user.daily_minutes == 180
        assert user.warnings == [15, 10, 5, 1]
