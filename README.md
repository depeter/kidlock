# Kidlock - Parental Screen Control via MQTT

A cross-platform (Linux + Windows) parental control agent that integrates with Home Assistant via MQTT.

## Features

- **Lock/unlock screen** - Remotely lock the computer
- **Shutdown/restart** - With configurable delay and warning popup
- **Activity tracking** - Active window title + idle time
- **Time limits** - Auto-lock after X hours of daily use
- **Schedule** - Allowed usage hours (weekday/weekend)
- **Website blocking** - DNS-based whitelist mode (Linux only, via dnsmasq)
- **Remote settings** - Update limits and schedules from Home Assistant
- **LWT** - Offline detection via MQTT Last Will Testament

## Requirements

- Python 3.8+
- MQTT broker (e.g., Mosquitto in Home Assistant)

### Linux Dependencies

The install script automatically installs all dependencies (supports apt, dnf, pacman):
- `xdotool` - Window detection
- `xprintidle` - Idle time tracking
- `zenity` - Warning popups
- `dnsmasq` - DNS-based website blocking

### Windows Dependencies

No additional dependencies required (uses Win32 API).

**Note:** Website blocking is currently only supported on Linux.

## Installation

### Linux

```bash
cd kidlock
chmod +x install-linux.sh
./install-linux.sh
```

### Windows

Run PowerShell as Administrator:

```powershell
cd kidlock
powershell -ExecutionPolicy Bypass -File install-windows.ps1
```

## Configuration

Edit `~/.config/kidlock/config.yaml` (Linux) or `%LOCALAPPDATA%\kidlock\config.yaml` (Windows):

```yaml
mqtt:
  broker: "homeassistant.local"
  port: 1883
  username: "mqtt_user"
  password: "mqtt_pass"

# device:
#   hostname: "custom-name"  # Optional: defaults to system hostname

activity:
  poll_interval: 10  # Seconds

limits:
  daily_minutes: 180  # 3 hours (0 = unlimited)
  schedule:
    weekday: "15:00-20:00"
    weekend: "09:00-21:00"
```

## MQTT Topics

| Topic | Description |
|-------|-------------|
| `parental/{hostname}/status` | Device status (online/offline) |
| `parental/{hostname}/activity` | Active window, idle time, usage, blocking status |
| `parental/{hostname}/command` | Command input |
| `parental/{hostname}/settings` | Settings input (limits, schedule, blocking) |

### Status Payload

```json
{"state": "online"}
```

### Activity Payload

```json
{
  "active_window": "Firefox",
  "idle_seconds": 45,
  "usage_minutes": 87,
  "blocking_enabled": true
}
```

### Settings Payload

Settings are typically sent from Home Assistant to update limits and blocking:

```json
{
  "daily_minutes": 180,
  "weekday_start": "15:00:00",
  "weekday_end": "20:00:00",
  "weekend_start": "09:00:00",
  "weekend_end": "21:00:00",
  "blocking_enabled": true,
  "whitelist": "google.com, youtube.com, wikipedia.org"
}
```

### Commands

Lock screen:
```json
{"action": "lock"}
```

Shutdown with warning:
```json
{"action": "shutdown", "delay": 60, "warning": true}
```

Restart:
```json
{"action": "restart", "delay": 30, "warning": true}
```

Cancel pending shutdown:
```json
{"action": "cancel"}
```

Unlock screen (Windows only):
```json
{"action": "unlock"}
```

## Website Blocking (Linux)

DNS-based website blocking uses dnsmasq to implement a whitelist mode. When enabled:
- All domains are blocked by default (return NXDOMAIN)
- Only whitelisted domains can resolve via upstream DNS (8.8.8.8)
- Includes default whitelist: google.com, googleapis.com, gstatic.com, duckduckgo.com, wikipedia.org, wikimedia.org, cloudflare.com, akamaihd.net

Control via Home Assistant:
- Toggle `input_boolean.kidlock_blocking_enabled` to enable/disable
- Edit `input_text.kidlock_whitelist` with comma-separated domains

The installer configures:
- NetworkManager to use local dnsmasq for DNS
- Sudoers rules for passwordless dnsmasq management

## Home Assistant Setup

Copy `homeassistant/kidlock.yaml` to your Home Assistant config:

```bash
cp homeassistant/kidlock.yaml /config/packages/kidlock.yaml
```

Add to `configuration.yaml`:

```yaml
homeassistant:
  packages:
    kidlock: !include packages/kidlock.yaml
```

Restart Home Assistant.

## Manual Testing

```bash
# Linux
python3 -m agent.main -c ~/.config/kidlock/config.yaml -v

# Windows
python -m agent.main -c %LOCALAPPDATA%\kidlock\config.yaml -v
```

## Service Management

### Linux (systemd)

```bash
systemctl --user enable kidlock
systemctl --user start kidlock
systemctl --user status kidlock
journalctl --user -u kidlock -f
```

### Windows (Task Scheduler)

```powershell
Start-ScheduledTask -TaskName Kidlock
Get-ScheduledTask -TaskName Kidlock
Stop-ScheduledTask -TaskName Kidlock
```

## Troubleshooting

### Linux: Screen lock not working

Try alternative commands:
```bash
# Test each to see which works
loginctl lock-session
xdg-screensaver lock
gnome-screensaver-command -l
```

### Windows: Scheduled task not starting

1. Open Task Scheduler
2. Find "Kidlock" task
3. Right-click → Run
4. Check "History" tab for errors

### MQTT connection issues

1. Verify broker address and credentials
2. Check broker logs
3. Test with `mosquitto_pub`/`mosquitto_sub`
