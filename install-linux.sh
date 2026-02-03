#!/bin/bash
# Kidlock Linux installer - installs as systemd user service

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="kidlock"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== Kidlock Linux Installer ==="

# Check if running as root (shouldn't be)
if [ "$EUID" -eq 0 ]; then
    echo "Error: Do not run this script as root or with sudo."
    echo "Run as your normal user: ./install-linux.sh"
    echo "The script will use sudo internally when needed."
    exit 1
fi

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

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
if ! systemctl --user daemon-reload 2>/dev/null; then
    echo "Note: Could not reload systemd user daemon."
    echo "      Run 'systemctl --user daemon-reload' after logging in to your desktop."
fi

# Setup DNS blocking with dnsmasq (via NetworkManager plugin)
echo ""
echo "=== Setting up DNS blocking ==="

# NetworkManager uses its own dnsmasq instance, configs go in /etc/NetworkManager/dnsmasq.d/
sudo mkdir -p /etc/NetworkManager/dnsmasq.d

# Create empty kidlock config (will be populated when blocking is enabled)
echo "Configuring dnsmasq..."
sudo tee /etc/NetworkManager/dnsmasq.d/kidlock.conf > /dev/null << 'EOF'
# Kidlock DNS blocking disabled
EOF

# Configure sudoers for kidlock DNS operations
echo "Configuring sudoers for DNS blocking..."
sudo tee /etc/sudoers.d/kidlock > /dev/null << EOF
# Kidlock parental control - allow managing DNS blocking
$USER ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/NetworkManager/dnsmasq.d/kidlock.conf
$USER ALL=(ALL) NOPASSWD: /bin/systemctl restart NetworkManager
EOF

# Configure NetworkManager to use dnsmasq plugin
echo "Configuring NetworkManager to use dnsmasq..."
sudo tee /etc/NetworkManager/conf.d/kidlock-dns.conf > /dev/null << 'EOF'
[main]
dns=dnsmasq
EOF

# Restart NetworkManager to apply changes
echo "Restarting NetworkManager..."
sudo systemctl restart NetworkManager

echo ""
echo "=== Configuration ==="
echo ""
echo "Opening config file for editing..."
echo "Set your MQTT broker, username, and password."
echo ""
read -p "Press Enter to open nano..."
nano "$CONFIG_DIR/config.yaml"

echo ""
echo "=== Service Setup ==="
echo ""
read -p "Enable and start kidlock service now? [Y/n] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"
    echo "Service enabled and started."

    read -p "Enable service to start at boot (before login)? [Y/n] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        sudo loginctl enable-linger "$USER"
        echo "Linger enabled - service will start at boot."
    fi
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Useful commands:"
echo "  Status:  systemctl --user status $SERVICE_NAME"
echo "  Logs:    journalctl --user -u $SERVICE_NAME -f"
echo "  Stop:    systemctl --user stop $SERVICE_NAME"
echo "  Restart: systemctl --user restart $SERVICE_NAME"
echo "  Config:  nano $CONFIG_DIR/config.yaml"
