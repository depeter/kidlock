#!/usr/bin/env python3
"""Kidlock system tray indicator showing remaining screen time."""

import json
import os
import signal
import sys
import threading
import time
from datetime import date
from pathlib import Path

# Try to import required modules
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Required packages not installed. Install with:")
    print("  pip install pystray pillow")
    sys.exit(1)


# Configuration
STATE_FILE = Path("/var/lib/kidlock/state.json")
CONFIG_FILE = Path("/etc/kidlock/config.yaml")
REQUEST_DIR = Path("/var/lib/kidlock/requests")
UPDATE_INTERVAL = 30  # seconds

# Colors (RGB)
COLOR_GREEN = (76, 175, 80)      # >30 min remaining
COLOR_YELLOW = (255, 193, 7)     # 10-30 min remaining
COLOR_RED = (244, 67, 54)        # <10 min remaining
COLOR_GRAY = (158, 158, 158)     # Offline/unknown
COLOR_BLUE = (33, 150, 243)      # Paused


def get_username():
    """Get current username."""
    return os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"


def load_config():
    """Load kidlock configuration."""
    try:
        import yaml
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                return yaml.safe_load(f)
    except ImportError:
        # Fallback: parse YAML manually for simple cases
        pass
    except Exception:
        pass
    return None


def get_user_config(config, username):
    """Get config for specific user."""
    if not config or "users" not in config:
        return None
    for user in config.get("users", []):
        if user.get("username") == username:
            return user
    return None


def load_state():
    """Load state from state file."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def get_user_state(username):
    """Get state for current user."""
    state = load_state()
    if not state:
        return None

    user_data = state.get("users", {}).get(username, {})
    if not user_data:
        return None

    # Check if state is from today
    today = date.today().isoformat()
    if user_data.get("last_usage_date") != today:
        # New day - reset
        return {
            "usage_minutes": 0,
            "paused": False,
            "bonus_minutes": 0,
        }

    return user_data


def get_time_info(username):
    """Get time remaining and related info.

    Returns (remaining_minutes, total_limit, paused, status_text)
    Returns (None, None, False, "Unknown") if can't determine
    """
    config = load_config()
    user_config = get_user_config(config, username)

    if not user_config:
        return None, None, False, "Not Configured"

    daily_limit = user_config.get("daily_minutes", 0)
    if daily_limit <= 0:
        return None, None, False, "Unlimited"

    user_state = get_user_state(username)
    if not user_state:
        return daily_limit, daily_limit, False, "Ready"

    usage = user_state.get("usage_minutes", 0)
    bonus = user_state.get("bonus_minutes", 0)
    paused = user_state.get("paused", False)

    total_limit = daily_limit + bonus
    remaining = max(0, total_limit - usage)

    if paused:
        status = "Paused"
    elif remaining <= 0:
        status = "Time's Up"
    else:
        status = "Playing"

    return remaining, total_limit, paused, status


def format_time(minutes):
    """Format minutes as human-readable string."""
    if minutes is None:
        return "?"
    if minutes < 0:
        return "Unlimited"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def get_color_for_remaining(remaining, paused):
    """Get appropriate color based on remaining time."""
    if paused:
        return COLOR_BLUE
    if remaining is None:
        return COLOR_GRAY
    if remaining > 30:
        return COLOR_GREEN
    if remaining > 10:
        return COLOR_YELLOW
    return COLOR_RED


def create_icon(remaining, paused, size=64):
    """Create tray icon showing remaining time."""
    # Create image with transparent background
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Background circle
    margin = 2
    color = get_color_for_remaining(remaining, paused)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color
    )

    # Text in center
    if remaining is not None:
        if remaining >= 60:
            text = f"{remaining // 60}h"
        else:
            text = f"{remaining}"
    else:
        text = "?"

    # Try to use a nice font, fall back to default
    font = None
    font_size = size // 3
    try:
        # Try common system fonts
        for font_name in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            if os.path.exists(font_name):
                font = ImageFont.truetype(font_name, font_size)
                break
    except Exception:
        pass

    if font is None:
        font = ImageFont.load_default()

    # Center text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 2
    draw.text((x, y), text, fill="white", font=font)

    # Add pause indicator if paused
    if paused:
        # Draw pause bars
        bar_width = size // 8
        bar_height = size // 4
        bar_y = size - bar_height - margin - 2
        draw.rectangle(
            [size // 3 - bar_width, bar_y, size // 3, bar_y + bar_height],
            fill="white"
        )
        draw.rectangle(
            [size * 2 // 3 - bar_width, bar_y, size * 2 // 3, bar_y + bar_height],
            fill="white"
        )

    return image


class KidlockTray:
    """System tray application for Kidlock."""

    def __init__(self):
        self.username = get_username()
        self.running = True
        self.icon = None
        self._update_lock = threading.Lock()

    def get_tooltip(self):
        """Get tooltip text."""
        remaining, total, paused, status = get_time_info(self.username)

        lines = [f"Kidlock - {self.username}"]
        lines.append(f"Status: {status}")

        if remaining is not None and total is not None:
            usage = total - remaining
            lines.append(f"Used: {format_time(usage)} of {format_time(total)}")
            lines.append(f"Remaining: {format_time(remaining)}")

        return "\n".join(lines)

    def update_icon(self):
        """Update the tray icon."""
        if not self.icon:
            return

        remaining, total, paused, status = get_time_info(self.username)

        with self._update_lock:
            try:
                new_image = create_icon(remaining, paused)
                self.icon.icon = new_image
                self.icon.title = self.get_tooltip()
            except Exception as e:
                print(f"Error updating icon: {e}")

    def update_loop(self):
        """Background thread to update icon periodically."""
        while self.running:
            self.update_icon()
            time.sleep(UPDATE_INTERVAL)

    def on_quit(self, icon, item):
        """Handle quit menu item."""
        self.running = False
        icon.stop()

    def on_request_time(self, icon, item):
        """Handle request time menu item."""
        # Check if already has pending request
        user_state = get_user_state(self.username)
        if user_state and user_state.get("pending_request"):
            self._show_message("Request Pending", "You already have a pending request.")
            return

        # Write request file for agent to pick up
        try:
            REQUEST_DIR.mkdir(parents=True, exist_ok=True)
            request_file = REQUEST_DIR / f"{self.username}.json"
            request_data = {
                "username": self.username,
                "minutes": 15,  # Default request
                "reason": "",
            }
            with open(request_file, "w") as f:
                json.dump(request_data, f)
            # Make writable by all (agent runs as root)
            os.chmod(request_file, 0o666)
            self._show_message("Request Sent", "Your request for 15 extra minutes has been sent.")
        except Exception as e:
            self._show_message("Error", f"Failed to send request: {e}")

    def _show_message(self, title, message):
        """Show a message to the user."""
        try:
            import subprocess
            subprocess.Popen(
                ["notify-send", "--app-name=Kidlock", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _has_pending_request(self):
        """Check if user has pending request."""
        user_state = get_user_state(self.username)
        return user_state and user_state.get("pending_request") is not None

    def create_menu(self):
        """Create tray menu."""
        has_request = self._has_pending_request()
        return pystray.Menu(
            pystray.MenuItem("Kidlock Screen Time", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Request Pending..." if has_request else "Request +15 Minutes",
                self.on_request_time,
                enabled=not has_request,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.on_quit),
        )

    def run(self):
        """Run the tray application."""
        # Initial icon
        remaining, total, paused, status = get_time_info(self.username)
        image = create_icon(remaining, paused)

        # Create tray icon
        self.icon = pystray.Icon(
            "kidlock",
            image,
            self.get_tooltip(),
            menu=self.create_menu(),
        )

        # Start update thread
        update_thread = threading.Thread(target=self.update_loop, daemon=True)
        update_thread.start()

        # Handle signals
        def signal_handler(sig, frame):
            self.running = False
            if self.icon:
                self.icon.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Run (blocks)
        self.icon.run()


def main():
    username = get_username()

    # Check if user is controlled by kidlock
    config = load_config()
    user_config = get_user_config(config, username)

    if not user_config:
        print(f"User '{username}' is not controlled by Kidlock. Exiting.")
        sys.exit(0)

    print(f"Starting Kidlock tray for user: {username}")
    app = KidlockTray()
    app.run()


if __name__ == "__main__":
    main()
