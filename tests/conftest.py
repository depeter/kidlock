"""Pytest configuration and shared fixtures."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_state_file():
    """Create a temporary state file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        state = {
            "users": {
                "testuser": {
                    "usage_minutes": 60,
                    "last_usage_date": "2024-01-15",
                    "blocked": False,
                    "block_reason": "",
                    "paused": False,
                    "paused_at": None,
                    "bonus_minutes": 0,
                    "warnings_sent": [],
                    "pending_request": None,
                }
            }
        }
        json.dump(state, f)
        f.flush()
        yield Path(f.name)


@pytest.fixture
def temp_config_file():
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config = """
mqtt:
  broker: "localhost"
  port: 1883
  username: "test"
  password: "test"

users:
  - username: "testuser"
    daily_minutes: 120
    schedule:
      weekday: "15:00-20:00"
      weekend: "09:00-21:00"
    warnings: [10, 5, 1]

activity:
  poll_interval: 10
  pause_auto_resume: 30
"""
        f.write(config)
        f.flush()
        yield Path(f.name)


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for tests that call external commands."""
    mock = MagicMock()
    mock.return_value.returncode = 0
    mock.return_value.stdout = ""
    mock.return_value.stderr = ""
    return mock
