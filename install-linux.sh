#!/bin/bash
# Kidlock Linux installer - installs as systemd user service

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="kidlock"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== Kidlock Linux Installer ==="

# Detect package manager and install function
install_pkg() {
    if command -v apt &>/dev/null; then
        sudo apt install -y "$@"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$@"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm "$@"
    else
        echo "Error: No supported package manager found (apt, dnf, pacman)"
        exit 1
    fi
}

# Install all required system dependencies
echo "Checking and installing dependencies..."
DEPS_TO_INSTALL=()

# Check for Python
if ! command -v python3 &>/dev/null; then
    echo "python3 not found, will install..."
    DEPS_TO_INSTALL+=(python3)
    # On apt systems, python3-venv is a separate package
    if command -v apt &>/dev/null; then
        DEPS_TO_INSTALL+=(python3-venv)
    fi
elif ! python3 -m venv --help &>/dev/null 2>&1; then
    # Python exists but venv module missing (common on Debian/Ubuntu)
    echo "python3-venv not found, will install..."
    if command -v apt &>/dev/null; then
        DEPS_TO_INSTALL+=(python3-venv)
    fi
fi
# Note: dnf/pacman include venv in python3 package

# Check for required tools
for cmd in xdotool xprintidle zenity dnsmasq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "$cmd not found, will install..."
        DEPS_TO_INSTALL+=("$cmd")
    fi
done

# Install missing dependencies
if [ ${#DEPS_TO_INSTALL[@]} -gt 0 ]; then
    echo "Installing: ${DEPS_TO_INSTALL[*]}"
    install_pkg "${DEPS_TO_INSTALL[@]}"
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

# Setup DNS blocking with dnsmasq
echo ""
echo "=== Setting up DNS blocking ==="

# Configure dnsmasq base settings
echo "Configuring dnsmasq..."
sudo tee /etc/dnsmasq.d/00-kidlock-base.conf > /dev/null << 'EOF'
# Kidlock base configuration
# Only DNS, no DHCP
no-dhcp-interface=
# Listen on localhost
listen-address=127.0.0.1
bind-interfaces
EOF

# Create empty kidlock config
sudo tee /etc/dnsmasq.d/kidlock.conf > /dev/null << 'EOF'
# Kidlock DNS blocking disabled
EOF

# Configure sudoers for kidlock DNS operations
echo "Configuring sudoers for DNS blocking..."
sudo tee /etc/sudoers.d/kidlock > /dev/null << EOF
# Kidlock parental control - allow managing DNS blocking
$USER ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/dnsmasq.d/kidlock.conf
$USER ALL=(ALL) NOPASSWD: /bin/systemctl restart dnsmasq
$USER ALL=(ALL) NOPASSWD: /bin/systemctl stop dnsmasq
$USER ALL=(ALL) NOPASSWD: /bin/systemctl start dnsmasq
EOF

# Configure NetworkManager to use local dnsmasq
echo "Configuring NetworkManager to use local DNS..."
sudo tee /etc/NetworkManager/conf.d/kidlock-dns.conf > /dev/null << 'EOF'
[main]
dns=dnsmasq
EOF

# Restart services
echo "Restarting NetworkManager and dnsmasq..."
sudo systemctl restart NetworkManager
sudo systemctl enable dnsmasq
sudo systemctl restart dnsmasq

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
