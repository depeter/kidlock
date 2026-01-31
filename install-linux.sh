#!/bin/bash
# Kidlock Linux installer - installs as systemd user service

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="kidlock"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== Kidlock Linux Installer ==="

# Check for required tools
echo "Checking dependencies..."
for cmd in xdotool xprintidle zenity; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Warning: $cmd not found. Install with: sudo apt install $cmd"
    fi
done

# Check for Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# Install Python dependencies
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# Create config directory
CONFIG_DIR="$HOME/.config/kidlock"
mkdir -p "$CONFIG_DIR"

# Copy example config if no config exists
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    echo "Creating config from example..."
    cp "$SCRIPT_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
    echo "Please edit $CONFIG_DIR/config.yaml with your MQTT settings"
fi

# Create systemd user service
echo "Creating systemd user service..."
mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/$SERVICE_NAME.service" << EOF
[Unit]
Description=Kidlock Parental Control Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/python -m agent.main --config $CONFIG_DIR/config.yaml
WorkingDirectory=$SCRIPT_DIR
Restart=always
RestartSec=10
Environment=DISPLAY=:0
Environment=XAUTHORITY=$HOME/.Xauthority

[Install]
WantedBy=default.target
EOF

# Reload systemd
echo "Reloading systemd..."
systemctl --user daemon-reload

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit config: nano $CONFIG_DIR/config.yaml"
echo "2. Test manually: $VENV_DIR/bin/python -m agent.main -c $CONFIG_DIR/config.yaml -v"
echo "3. Enable service: systemctl --user enable $SERVICE_NAME"
echo "4. Start service: systemctl --user start $SERVICE_NAME"
echo "5. Check status: systemctl --user status $SERVICE_NAME"
echo "6. View logs: journalctl --user -u $SERVICE_NAME -f"
echo ""
echo "To enable service to start at boot (before login):"
echo "  sudo loginctl enable-linger $USER"
