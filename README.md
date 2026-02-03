# Kidlock - Parental Control via MQTT

A Linux parental control agent that integrates with Home Assistant via MQTT. Runs as a system service with PAM integration for effective enforcement.

## Features

- **Hard login blocking** - PAM integration prevents login outside allowed hours
- **Force logout** - Automatically logs out users when time limit reached
- **Time tracking** - Per-user daily usage tracking with persistent state
- **Schedule enforcement** - Weekday/weekend allowed hours
- **Website blocking** - DNS-based whitelist mode (via dnsmasq)
- **Remote control** - Lock/unlock users via MQTT from Home Assistant
- **Multi-user** - Control multiple users with individual limits
- **LWT** - Offline detection via MQTT Last Will Testament

## How It Works

1. **System service** runs as root - can't be stopped by controlled users
2. **PAM module** blocks login during restricted hours
3. **Continuous enforcement** checks every 10 seconds and force-logs out users who shouldn't be logged in
4. **State persistence** survives reboots - usage tracking continues

## Requirements

- Linux with systemd (Debian/Ubuntu/Mint, Fedora, Arch)
- Python 3.8+
- MQTT broker (e.g., Mosquitto in Home Assistant)
- NetworkManager (for DNS blocking)

## Installation

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

activity:
  poll_interval: 10  # Seconds between checks
```

### Multiple Users

```yaml
users:
  - username: "alice"
    daily_minutes: 120
    schedule:
      weekday: "16:00-19:00"
      weekend: "10:00-20:00"

  - username: "bob"
    daily_minutes: 180
    schedule:
      weekday: "15:00-20:00"
      weekend: "09:00-21:00"
```

## MQTT Topics

| Topic | Description |
|-------|-------------|
| `parental/{hostname}/status` | Device status (online/offline) |
| `parental/{hostname}/user/{username}` | Per-user activity and status |
| `parental/{hostname}/command` | Command input |
| `parental/{hostname}/settings` | Settings input |

### User Status Payload

```json
{
  "username": "kid",
  "active": true,
  "usage_minutes": 87,
  "daily_limit": 180,
  "blocked": false,
  "block_reason": "",
  "blocking_enabled": false
}
```

### Commands

Lock user (force logout):
```json
{"action": "lock", "user": "kid"}
```

Lock all controlled users:
```json
{"action": "lock"}
```

Unlock user (allow login again):
```json
{"action": "unlock", "user": "kid"}
```

Shutdown:
```json
{"action": "shutdown", "delay": 60}
```

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

## Security Notes

- Config file contains MQTT credentials - readable only by root
- Service runs as root for enforcement capability
- PAM integration affects all login methods (console, GUI, SSH)
- Controlled users cannot stop the service
