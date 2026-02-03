#!/bin/bash
# Kidlock Linux installer - installs as system service with PAM integration
# Must be run with sudo

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="kidlock"

echo "=== Kidlock Linux Installer ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "This installer must be run as root (with sudo)."
    echo "Usage: sudo ./install-linux.sh"
    exit 1
fi

# Get the actual user (not root)
if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
else
    echo "Error: Please run with sudo, not as root directly."
    exit 1
fi

# Detect package manager and install function
install_pkg() {
    if command -v apt &>/dev/null; then
        apt install -y "$@"
    elif command -v dnf &>/dev/null; then
        dnf install -y "$@"
    elif command -v pacman &>/dev/null; then
        pacman -S --noconfirm "$@"
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
    if command -v apt &>/dev/null; then
        DEPS_TO_INSTALL+=(python3-venv)
    fi
elif ! python3 -m venv --help &>/dev/null 2>&1; then
    echo "python3-venv not found, will install..."
    if command -v apt &>/dev/null; then
        DEPS_TO_INSTALL+=(python3-venv)
    fi
fi

# Check for dnsmasq (for DNS blocking)
if ! command -v dnsmasq &>/dev/null; then
    echo "dnsmasq not found, will install..."
    DEPS_TO_INSTALL+=(dnsmasq)
fi

# Check for libnotify (for desktop notifications)
if ! command -v notify-send &>/dev/null; then
    echo "libnotify not found, will install..."
    if command -v apt &>/dev/null; then
        DEPS_TO_INSTALL+=(libnotify-bin)
    elif command -v dnf &>/dev/null; then
        DEPS_TO_INSTALL+=(libnotify)
    elif command -v pacman &>/dev/null; then
        DEPS_TO_INSTALL+=(libnotify)
    fi
fi

# Install missing dependencies
if [ ${#DEPS_TO_INSTALL[@]} -gt 0 ]; then
    echo "Installing: ${DEPS_TO_INSTALL[*]}"
    install_pkg "${DEPS_TO_INSTALL[@]}"
fi

# Create installation directory
INSTALL_DIR="/opt/kidlock"
echo ""
echo "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/agent" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/tray" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/pam-check.py" "$INSTALL_DIR/"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"

# Install Python dependencies
echo "Installing Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Create config directory
CONFIG_DIR="/etc/kidlock"
mkdir -p "$CONFIG_DIR"

# Copy example config if no config exists
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    echo "Creating config from example..."
    cp "$SCRIPT_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
fi

# Create state directory (world-readable for tray app)
mkdir -p /var/lib/kidlock
chmod 755 /var/lib/kidlock
# Ensure state file is readable by all (for tray indicator)
if [ -f /var/lib/kidlock/state.json ]; then
    chmod 644 /var/lib/kidlock/state.json
fi

# Install PAM check script
echo "Installing PAM check script..."
cp "$INSTALL_DIR/pam-check.py" /usr/local/bin/kidlock-pam-check
chmod 755 /usr/local/bin/kidlock-pam-check

# Make tray script executable
chmod +x "$INSTALL_DIR/tray/kidlock-tray.py"

# Install tray dependencies in virtual environment
echo "Installing tray dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/tray/requirements.txt" 2>/dev/null || true

# Create systemd system service (hardened)
echo "Creating systemd system service..."
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=Kidlock Parental Control Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/.venv/bin/python -m agent.main
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/kidlock /etc/NetworkManager/dnsmasq.d
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Setup DNS blocking with dnsmasq (via NetworkManager plugin)
echo ""
echo "=== Setting up DNS blocking ==="

# NetworkManager uses its own dnsmasq instance
mkdir -p /etc/NetworkManager/dnsmasq.d

# Create empty kidlock config
echo "Configuring dnsmasq..."
tee /etc/NetworkManager/dnsmasq.d/kidlock.conf > /dev/null << 'EOF'
# Kidlock DNS blocking disabled
EOF

# Configure NetworkManager to use dnsmasq plugin
tee /etc/NetworkManager/conf.d/kidlock-dns.conf > /dev/null << 'EOF'
[main]
dns=dnsmasq
EOF

# Restart NetworkManager
echo "Restarting NetworkManager..."
systemctl restart NetworkManager

# Setup PAM integration
echo ""
echo "=== Setting up PAM integration ==="
echo "Adding kidlock check to PAM..."

PAM_LINE="auth    required    pam_exec.so    quiet /usr/local/bin/kidlock-pam-check"

# Add to common-auth if not already there (Debian/Ubuntu)
if [ -f /etc/pam.d/common-auth ]; then
    if ! grep -q "kidlock-pam-check" /etc/pam.d/common-auth; then
        # Insert after the first auth line
        sed -i "0,/^auth/s/^auth.*$/&\n$PAM_LINE/" /etc/pam.d/common-auth
        echo "Added to /etc/pam.d/common-auth"
    else
        echo "Already in /etc/pam.d/common-auth"
    fi
fi

# Also add to login and gdm/lightdm for redundancy
for pam_file in /etc/pam.d/login /etc/pam.d/gdm-password /etc/pam.d/lightdm; do
    if [ -f "$pam_file" ]; then
        if ! grep -q "kidlock-pam-check" "$pam_file"; then
            sed -i "0,/^auth/s/^auth.*$/&\n$PAM_LINE/" "$pam_file"
            echo "Added to $pam_file"
        fi
    fi
done

# ============================================================
# Setup Tray Indicator for Controlled Users
# ============================================================
echo ""
echo "=== Setting up Tray Indicator ==="

# Create tray launcher script that uses the venv
cat > /usr/local/bin/kidlock-tray << 'TRAY_EOF'
#!/bin/bash
exec /opt/kidlock/.venv/bin/python /opt/kidlock/tray/kidlock-tray.py "$@"
TRAY_EOF
chmod +x /usr/local/bin/kidlock-tray

# Function to setup tray autostart for a user
setup_tray_for_user() {
    local username="$1"
    local user_home=$(getent passwd "$username" | cut -d: -f6)

    if [ -z "$user_home" ] || [ ! -d "$user_home" ]; then
        echo "Warning: Could not find home directory for $username"
        return
    fi

    local autostart_dir="$user_home/.config/autostart"
    mkdir -p "$autostart_dir"

    # Create desktop file for autostart
    cat > "$autostart_dir/kidlock-tray.desktop" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Kidlock Time Indicator
Comment=Shows remaining screen time
Exec=/usr/local/bin/kidlock-tray
Icon=clock
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
DESKTOP_EOF

    chown "$username:" "$autostart_dir/kidlock-tray.desktop"
    echo "Installed tray autostart for $username"
}

# Parse config and setup tray for each controlled user
if [ -f "$CONFIG_DIR/config.yaml" ]; then
    # Extract usernames from config (simple grep - works for basic YAML)
    CONTROLLED_USERS=$(grep -E "^\s*-?\s*username:" "$CONFIG_DIR/config.yaml" | sed 's/.*username:\s*["'"'"']\?\([^"'"'"']*\)["'"'"']\?.*/\1/')
    for user in $CONTROLLED_USERS; do
        if id "$user" &>/dev/null; then
            setup_tray_for_user "$user"
        else
            echo "Note: User '$user' in config does not exist on this system"
        fi
    done
else
    echo "Config not found yet - tray will be set up after configuration"
fi

echo ""
echo "=== Configuration ==="
echo ""
echo "Opening config file for editing..."
echo "Configure your MQTT broker and the users to control."
echo ""
read -p "Press Enter to open nano..."
nano "$CONFIG_DIR/config.yaml"

# Re-run tray setup after config edit
if [ -f "$CONFIG_DIR/config.yaml" ]; then
    CONTROLLED_USERS=$(grep -E "^\s*-?\s*username:" "$CONFIG_DIR/config.yaml" | sed 's/.*username:\s*["'"'"']\?\([^"'"'"']*\)["'"'"']\?.*/\1/')
    for user in $CONTROLLED_USERS; do
        if id "$user" &>/dev/null; then
            setup_tray_for_user "$user"
        fi
    done
fi

echo ""
echo "=== Service Setup ==="
echo ""
read -p "Enable and start kidlock service now? [Y/n] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"
    echo "Service enabled and started."
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Kidlock is now running as a system service."
echo ""
echo "FEATURES:"
echo "  - Block login for controlled users outside allowed hours"
echo "  - Force logout when time limit is reached"
echo "  - Track usage time per user"
echo "  - Desktop warnings before time runs out"
echo "  - System tray indicator showing remaining time"
echo "  - Add bonus time via Home Assistant (+15min, +30min buttons)"
echo "  - Pause timer via Home Assistant"
echo ""
echo "USEFUL COMMANDS:"
echo "  Status:  systemctl status $SERVICE_NAME"
echo "  Logs:    journalctl -u $SERVICE_NAME -f"
echo "  Stop:    systemctl stop $SERVICE_NAME"
echo "  Restart: systemctl restart $SERVICE_NAME"
echo "  Config:  nano $CONFIG_DIR/config.yaml"
echo ""
echo "HOME ASSISTANT:"
echo "  Dashboard template: $SCRIPT_DIR/homeassistant/dashboard.yaml"
echo "  Automation examples: $SCRIPT_DIR/homeassistant/automations.yaml"
echo ""
echo "TRAY INDICATOR:"
echo "  The tray app will auto-start for controlled users."
echo "  Manual run: kidlock-tray"
echo ""
echo "To uninstall: sudo $SCRIPT_DIR/uninstall-linux.sh"
