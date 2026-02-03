# Kidlock - Parental Control via MQTT

A Linux parental control agent that integrates with Home Assistant via MQTT. Runs as a system service with PAM integration for effective enforcement.

## Features

### Enforcement
- **Hard login blocking** - PAM integration prevents login outside allowed hours
- **Force logout** - Automatically logs out users when time limit reached
- **Schedule enforcement** - Weekday/weekend allowed hours
- **Website blocking** - DNS-based whitelist mode (via dnsmasq)

### Time Management
- **Daily time limits** - Per-user configurable limits
- **Time tracking** - Persistent usage tracking that survives reboots
- **Pause/resume timer** - Temporarily pause the countdown (e.g., for homework)
- **Bonus time** - Add extra minutes on-the-fly from Home Assistant
- **Auto-resume** - Paused timers automatically resume after configurable timeout

### Notifications
- **Desktop notifications** - Warns users before time runs out (configurable thresholds)
- **System tray indicator** - Shows remaining time with color-coded icon (green/yellow/red)
- **Mobile notifications** - Example Home Assistant automations for parent alerts

### Home Assistant Integration
- **MQTT auto-discovery** - Entities appear automatically in Home Assistant
- **Remote control** - Lock/unlock, pause/resume, add time via MQTT
- **Real-time status** - Active/blocked state, usage, time remaining
- **Events** - Login/logout/warning events for automations
- **LWT** - Offline detection via MQTT Last Will Testament
- **Multi-user** - Control multiple users with individual limits

## How It Works

1. **System service** runs as root - can't be stopped by controlled users
2. **PAM module** blocks login during restricted hours
3. **Continuous enforcement** checks every 10 seconds and force-logs out users who shouldn't be logged in
4. **Desktop notifications** warn users before time runs out
5. **State persistence** survives reboots - usage and bonus time tracking continues
6. **Tray indicator** (optional) shows users their remaining time

## Requirements

- Linux with systemd (Debian/Ubuntu/Mint, Fedora, Arch)
- Python 3.8+
- MQTT broker (e.g., Mosquitto in Home Assistant)
- NetworkManager (for DNS blocking)

## Installation

### Option 1: Debian Package (Recommended)

Download or build the `.deb` package, then install:

```bash
sudo dpkg -i kidlock_1.0.0_all.deb
sudo apt-get install -f  # Install any missing dependencies
```

After installation, edit the config:
```bash
sudo nano /etc/kidlock/config.yaml
sudo systemctl restart kidlock
```

### Building the Package

Requires FPM (`sudo gem install fpm`) and python3-venv:

```bash
cd kidlock/packaging
./build-deb.sh
# Output: dist/kidlock_1.0.0_all.deb
```

### Option 2: Manual Installation

```bash
cd kidlock
sudo ./install-linux.sh
```

The installer will:
1. Install dependencies (python3, dnsmasq)
2. Install to `/opt/kidlock`
3. Create config at `/etc/kidlock/config.yaml`
4. Set up PAM integration for login blocking
5. Create and start systemd service
6. Open config for editing

## Configuration

Edit `/etc/kidlock/config.yaml`:

```yaml
mqtt:
  broker: "homeassistant.local"
  port: 1883
  username: "mqtt_user"
  password: "mqtt_pass"

# Users to control
users:
  - username: "kid"
    daily_minutes: 180        # 3 hours max (0 = unlimited)
    schedule:
      weekday: "15:00-20:00"  # Allowed hours on weekdays
      weekend: "09:00-21:00"  # Allowed hours on weekends
    warnings: [10, 5, 1]      # Desktop notifications at X minutes remaining

activity:
  poll_interval: 10           # Seconds between checks
  pause_auto_resume: 30       # Auto-resume paused timers after X minutes
```

### Multiple Users

```yaml
users:
  - username: "alice"
    daily_minutes: 120
    schedule:
      weekday: "16:00-19:00"
      weekend: "10:00-20:00"
    warnings: [15, 5, 1]      # Custom warning thresholds

  - username: "bob"
    daily_minutes: 180
    schedule:
      weekday: "15:00-20:00"
      weekend: "09:00-21:00"
    warnings: [10, 5, 1]
```

## Home Assistant Integration

Kidlock uses **MQTT auto-discovery** - entities appear automatically in Home Assistant when the agent connects. No manual configuration needed.

### Auto-created Entities (per device)

- `binary_sensor.kidlock_{hostname}_online` - Device connectivity

### Auto-created Entities (per user)

| Entity | Type | Description |
|--------|------|-------------|
| `binary_sensor.kidlock_{hostname}_{user}_active` | Binary Sensor | User logged in |
| `binary_sensor.kidlock_{hostname}_{user}_blocked` | Binary Sensor | User blocked |
| `sensor.kidlock_{hostname}_{user}_usage` | Sensor | Today's usage (minutes) |
| `sensor.kidlock_{hostname}_{user}_limit` | Sensor | Daily limit (minutes) |
| `sensor.kidlock_{hostname}_{user}_time_remaining` | Sensor | Time remaining (minutes) |
| `sensor.kidlock_{hostname}_{user}_status` | Sensor | Status (Playing/Paused/Blocked/Offline) |
| `switch.kidlock_{hostname}_{user}_paused` | Switch | Pause/resume timer |
| `button.kidlock_{hostname}_{user}_lock` | Button | Force logout user |
| `button.kidlock_{hostname}_{user}_unlock` | Button | Allow user to log in |
| `button.kidlock_{hostname}_{user}_add_15min` | Button | Add 15 minutes bonus time |
| `button.kidlock_{hostname}_{user}_add_30min` | Button | Add 30 minutes bonus time |

### MQTT Topics

| Topic | Description |
|-------|-------------|
| `parental/{hostname}/status` | Device status (online/offline) |
| `parental/{hostname}/user/{username}` | Per-user activity and status |
| `parental/{hostname}/event` | Events for automations |
| `parental/{hostname}/command` | Command input |
| `parental/{hostname}/settings` | Settings input |

### User Status Payload

```json
{
  "username": "kid",
  "active": true,
  "usage_minutes": 87,
  "daily_limit": 180,
  "time_remaining": 93,
  "status": "Playing",
  "blocked": false,
  "block_reason": "",
  "paused": false,
  "bonus_minutes": 0,
  "blocking_enabled": false
}
```

### Events

Events are published to `parental/{hostname}/event` for use in automations:

| Event | Description |
|-------|-------------|
| `login` | User logged in |
| `logout` | User logged out |
| `time_warning` | Time limit approaching (includes `minutes_remaining`) |
| `time_exhausted` | Time limit reached |
| `pause_changed` | Timer paused or resumed (includes `paused` boolean) |
| `bonus_time` | Bonus time added (includes `minutes`) |

### Commands

Lock user (force logout):
```json
{"action": "lock", "user": "kid"}
```

Unlock user (allow login again):
```json
{"action": "unlock", "user": "kid"}
```

Pause timer:
```json
{"action": "pause", "user": "kid"}
```

Resume timer:
```json
{"action": "resume", "user": "kid"}
```

Add bonus time:
```json
{"action": "add_time", "user": "kid", "minutes": 15}
```

Shutdown computer:
```json
{"action": "shutdown", "delay": 60}
```

Restart computer:
```json
{"action": "restart", "delay": 60}
```

Cancel scheduled shutdown:
```json
{"action": "cancel"}
```

Omit `user` to apply to all controlled users.

## System Tray Indicator

Controlled users see a tray icon showing their remaining time:

- **Green** - More than 30 minutes remaining
- **Yellow** - 10-30 minutes remaining
- **Red** - Less than 10 minutes remaining
- **Blue** - Timer is paused

The indicator reads from the shared state file and updates every 30 seconds.

### Manual Setup (if not auto-started)

```bash
cd /opt/kidlock/tray
pip install -r requirements.txt
./kidlock-tray.py
```

Or add `tray/kidlock-tray.desktop` to your autostart.

## Home Assistant Automations

Example automations are provided in `homeassistant/automations.yaml` for mobile notifications:

- **Login notification** - When child logs in
- **Time warnings** - At 15 and 5 minutes remaining
- **Time exhausted** - When screen time is up
- **Device offline** - When device goes offline
- **Pause/resume** - When timer state changes
- **Actionable notifications** - Quick buttons to add time
- **Daily summary** - Usage report at 9 PM

Copy and customize the automations, replacing `{hostname}`, `{username}`, and `{notify_service}` with your values.

## Website Blocking

DNS-based blocking uses NetworkManager's dnsmasq plugin. When enabled:
- All domains blocked by default
- Only whitelisted domains can resolve

Control via MQTT settings:
```json
{
  "blocking_enabled": true,
  "whitelist": "google.com, wikipedia.org, school.edu"
}
```

Default whitelist includes: google.com, googleapis.com, gstatic.com, duckduckgo.com, wikipedia.org, wikimedia.org, cloudflare.com, akamaihd.net

## Service Management

```bash
# Status
sudo systemctl status kidlock

# Logs
sudo journalctl -u kidlock -f

# Restart after config change
sudo systemctl restart kidlock

# Stop
sudo systemctl stop kidlock
```

## Uninstall

### Debian Package

```bash
sudo apt remove kidlock       # Keep config files
sudo apt purge kidlock        # Remove everything including config
```

### Manual Installation

```bash
sudo ./uninstall-linux.sh
```

## Troubleshooting

### User can still log in during blocked hours

1. Check PAM is configured: `grep kidlock /etc/pam.d/common-auth`
2. Check service is running: `systemctl status kidlock`
3. Check state file: `cat /var/lib/kidlock/state.json`

### Service won't start

1. Check config syntax: `python3 -c "import yaml; yaml.safe_load(open('/etc/kidlock/config.yaml'))"`
2. Check logs: `journalctl -u kidlock -e`

### MQTT connection issues

1. Verify broker address and credentials
2. Check broker logs
3. Test with `mosquitto_pub`/`mosquitto_sub`

### Desktop notifications not showing

1. Check `notify-send` is installed: `which notify-send`
2. Check user has a display session: `loginctl list-sessions`
3. Service runs as root; it uses `sudo -u {user}` to send notifications

### Tray indicator not showing time

1. Check state file is readable: `ls -la /var/lib/kidlock/state.json`
2. Check user is configured in `/etc/kidlock/config.yaml`
3. Install dependencies: `pip install pystray pillow`

## Security Notes

- Config file contains MQTT credentials - readable only by root
- Service runs as root for enforcement capability
- PAM integration affects all login methods (console, GUI, SSH)
- Controlled users cannot stop the service
- Systemd service is hardened with security directives (verify with `systemd-analyze security kidlock`)
