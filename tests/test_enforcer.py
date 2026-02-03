"""Tests for enforcer module."""

import json
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent.config import ScheduleConfig, UserConfig
from agent.enforcer import Enforcer, UserState, STATE_FILE


class TestUserState:
    """Tests for UserState class."""

    def test_default_state(self):
        """Test default user state values."""
        state = UserState("testuser")

        assert state.username == "testuser"
        assert state.usage_minutes == 0
        assert state.last_usage_date is None
        assert state.blocked is False
        assert state.paused is False
        assert state.bonus_minutes == 0
        assert state.warnings_sent == set()

    def test_to_dict(self):
        """Test serialization to dict."""
        state = UserState("testuser")
        state.usage_minutes = 60
        state.paused = True
        state.warnings_sent = {10, 5}

        data = state.to_dict()

        assert data["usage_minutes"] == 60
        assert data["paused"] is True
        assert set(data["warnings_sent"]) == {10, 5}

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "usage_minutes": 45,
            "last_usage_date": "2024-01-15",
            "blocked": True,
            "block_reason": "Time limit",
            "paused": False,
            "bonus_minutes": 15,
            "warnings_sent": [10],
        }

        state = UserState.from_dict("testuser", data)

        assert state.username == "testuser"
        assert state.usage_minutes == 45
        assert state.blocked is True
        assert state.bonus_minutes == 15
        assert state.warnings_sent == {10}


class TestEnforcer:
    """Tests for Enforcer class."""

    @pytest.fixture
    def enforcer(self, tmp_path, monkeypatch):
        """Create an Enforcer with a temporary state directory."""
        state_dir = tmp_path / "kidlock"
        state_dir.mkdir()
        state_file = state_dir / "state.json"

        monkeypatch.setattr("agent.enforcer.STATE_DIR", state_dir)
        monkeypatch.setattr("agent.enforcer.STATE_FILE", state_file)

        return Enforcer()

    def test_get_user_state_creates_new(self, enforcer):
        """Test that get_user_state creates a new state if needed."""
        state = enforcer.get_user_state("newuser")

        assert state.username == "newuser"
        assert state.usage_minutes == 0

    def test_add_usage(self, enforcer):
        """Test adding usage time."""
        enforcer.add_usage("testuser", 10)

        state = enforcer.get_user_state("testuser")
        assert state.usage_minutes == 10

        enforcer.add_usage("testuser", 5)
        assert state.usage_minutes == 15

    def test_add_bonus_time(self, enforcer):
        """Test adding bonus time."""
        enforcer.add_bonus_time("testuser", 15)

        state = enforcer.get_user_state("testuser")
        assert state.bonus_minutes == 15

        enforcer.add_bonus_time("testuser", 10)
        assert state.bonus_minutes == 25

    def test_set_paused(self, enforcer):
        """Test pausing and resuming timer."""
        enforcer.set_paused("testuser", True)
        assert enforcer.is_paused("testuser") is True

        state = enforcer.get_user_state("testuser")
        assert state.paused_at is not None

        enforcer.set_paused("testuser", False)
        assert enforcer.is_paused("testuser") is False
        assert state.paused_at is None

    def test_get_time_remaining_unlimited(self, enforcer):
        """Test time remaining with no limit."""
        remaining = enforcer.get_time_remaining("testuser", 0)
        assert remaining == -1

    def test_get_time_remaining_with_limit(self, enforcer):
        """Test time remaining with a limit."""
        enforcer.add_usage("testuser", 60)
        remaining = enforcer.get_time_remaining("testuser", 120)
        assert remaining == 60

    def test_get_time_remaining_with_bonus(self, enforcer):
        """Test time remaining includes bonus time."""
        enforcer.add_usage("testuser", 100)
        enforcer.add_bonus_time("testuser", 30)

        remaining = enforcer.get_time_remaining("testuser", 120)
        assert remaining == 50  # 120 + 30 - 100

    def test_check_user_within_schedule_and_limit(self, enforcer):
        """Test user allowed when within schedule and limit."""
        user_config = UserConfig(
            username="testuser",
            daily_minutes=120,
            schedule=ScheduleConfig(weekday="00:00-23:59", weekend="00:00-23:59"),
        )

        enforcer.add_usage("testuser", 60)
        allowed, reason = enforcer.check_user(user_config)

        assert allowed is True
        assert reason == ""

    def test_check_user_limit_exceeded(self, enforcer):
        """Test user denied when limit exceeded."""
        user_config = UserConfig(
            username="testuser",
            daily_minutes=60,
            schedule=ScheduleConfig(weekday="00:00-23:59", weekend="00:00-23:59"),
        )

        enforcer.add_usage("testuser", 60)
        allowed, reason = enforcer.check_user(user_config)

        assert allowed is False
        assert "limit" in reason.lower()

    def test_check_user_bonus_extends_limit(self, enforcer):
        """Test bonus time extends the daily limit."""
        user_config = UserConfig(
            username="testuser",
            daily_minutes=60,
            schedule=ScheduleConfig(weekday="00:00-23:59", weekend="00:00-23:59"),
        )

        enforcer.add_usage("testuser", 60)
        enforcer.add_bonus_time("testuser", 30)

        allowed, reason = enforcer.check_user(user_config)
        assert allowed is True

    def test_get_warnings_to_send(self, enforcer):
        """Test getting warnings that should be sent."""
        enforcer.add_usage("testuser", 115)  # 5 min remaining of 120

        warnings = enforcer.get_warnings_to_send("testuser", 120, [10, 5, 1])
        assert 10 in warnings
        assert 5 in warnings
        assert 1 not in warnings

    def test_mark_warning_sent(self, enforcer):
        """Test marking a warning as sent."""
        enforcer.mark_warning_sent("testuser", 10)

        state = enforcer.get_user_state("testuser")
        assert 10 in state.warnings_sent

        # Should not return already-sent warnings
        enforcer.add_usage("testuser", 115)
        warnings = enforcer.get_warnings_to_send("testuser", 120, [10, 5, 1])
        assert 10 not in warnings

    def test_unblock_user(self, enforcer):
        """Test unblocking a user."""
        state = enforcer.get_user_state("testuser")
        state.blocked = True
        state.block_reason = "Test"

        enforcer.unblock_user("testuser")

        assert state.blocked is False
        assert state.block_reason == ""


class TestScheduleEnforcement:
    """Tests for schedule-related enforcement."""

    @pytest.fixture
    def enforcer(self, tmp_path, monkeypatch):
        """Create an Enforcer with a temporary state directory."""
        state_dir = tmp_path / "kidlock"
        state_dir.mkdir()
        state_file = state_dir / "state.json"

        monkeypatch.setattr("agent.enforcer.STATE_DIR", state_dir)
        monkeypatch.setattr("agent.enforcer.STATE_FILE", state_file)

        return Enforcer()

    def test_is_within_schedule_valid_time(self, enforcer):
        """Test schedule check with valid time format."""
        schedule = ScheduleConfig(weekday="09:00-17:00", weekend="10:00-20:00")

        # Mock datetime to control the time
        with patch("agent.enforcer.datetime") as mock_dt:
            # Monday at 12:00
            mock_dt.now.return_value = datetime(2024, 1, 15, 12, 0)
            mock_dt.strptime = datetime.strptime

            result = enforcer.is_within_schedule(schedule)
            assert result is True

    def test_is_within_schedule_outside_hours(self, enforcer):
        """Test schedule check outside allowed hours."""
        schedule = ScheduleConfig(weekday="09:00-17:00", weekend="10:00-20:00")

        with patch("agent.enforcer.datetime") as mock_dt:
            # Monday at 20:00 (8 PM, outside 9-5)
            mock_dt.now.return_value = datetime(2024, 1, 15, 20, 0)
            mock_dt.strptime = datetime.strptime

            result = enforcer.is_within_schedule(schedule)
            assert result is False

    def test_is_within_schedule_weekend(self, enforcer):
        """Test schedule check uses weekend hours on Saturday."""
        schedule = ScheduleConfig(weekday="15:00-20:00", weekend="09:00-21:00")

        with patch("agent.enforcer.datetime") as mock_dt:
            # Saturday at 10:00 (within weekend hours, outside weekday)
            mock_dt.now.return_value = datetime(2024, 1, 13, 10, 0)  # Saturday
            mock_dt.strptime = datetime.strptime

            result = enforcer.is_within_schedule(schedule)
            assert result is True

    def test_is_within_schedule_invalid_format(self, enforcer):
        """Test schedule check with invalid format defaults to allow."""
        schedule = ScheduleConfig(weekday="invalid", weekend="09:00-21:00")

        with patch("agent.enforcer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 12, 0)  # Monday
            mock_dt.strptime = datetime.strptime

            # Should allow on parse error
            result = enforcer.is_within_schedule(schedule)
            assert result is True
