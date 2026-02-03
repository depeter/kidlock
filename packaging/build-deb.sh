#!/bin/bash
# Build script for kidlock .deb package using FPM
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="1.0.0"
BUILD_DIR="$SCRIPT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"

echo "=== Building Kidlock .deb package v$VERSION ==="

# Check for FPM
if ! command -v fpm &>/dev/null; then
    echo "Error: FPM not found. Install with: sudo gem install fpm"
    exit 1
fi

# Check for python3-venv
if ! python3 -m venv --help &>/dev/null 2>&1; then
    echo "Error: python3-venv not found. Install with: sudo apt install python3-venv"
    exit 1
fi

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
mkdir -p "$DIST_DIR"

echo "Creating package structure..."

# Create directory structure
mkdir -p "$BUILD_DIR/opt/kidlock"
mkdir -p "$BUILD_DIR/etc/kidlock"
mkdir -p "$BUILD_DIR/etc/systemd/system"
mkdir -p "$BUILD_DIR/var/lib/kidlock"

# Copy application files
cp -r "$PROJECT_DIR/agent" "$BUILD_DIR/opt/kidlock/"
cp -r "$PROJECT_DIR/tray" "$BUILD_DIR/opt/kidlock/"
cp "$PROJECT_DIR/requirements.txt" "$BUILD_DIR/opt/kidlock/"
cp "$PROJECT_DIR/pam-check.py" "$BUILD_DIR/opt/kidlock/"
cp "$PROJECT_DIR/config.example.yaml" "$BUILD_DIR/opt/kidlock/"

# Create Python virtual environment with dependencies
echo "Creating virtual environment and installing dependencies..."
python3 -m venv "$BUILD_DIR/opt/kidlock/.venv"
"$BUILD_DIR/opt/kidlock/.venv/bin/pip" install --upgrade pip wheel
"$BUILD_DIR/opt/kidlock/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
"$BUILD_DIR/opt/kidlock/.venv/bin/pip" install -r "$PROJECT_DIR/tray/requirements.txt"

# Install systemd service file (hardened)
cat > "$BUILD_DIR/etc/systemd/system/kidlock.service" << 'EOF'
[Unit]
Description=Kidlock Parental Control Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/kidlock/.venv/bin/python -m agent.main
WorkingDirectory=/opt/kidlock
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

# Make scripts executable
chmod +x "$BUILD_DIR/opt/kidlock/tray/kidlock-tray.py"

echo "Building .deb package with FPM..."

# Build the package
fpm -s dir -t deb \
    --name kidlock \
    --version "$VERSION" \
    --architecture all \
    --maintainer "Peter <peter@pm-consulting.be>" \
    --description "Linux parental control with Home Assistant integration" \
    --url "https://github.com/peter/kidlock" \
    --license "MIT" \
    --depends "python3 >= 3.11" \
    --depends "python3-venv" \
    --depends "dnsmasq" \
    --depends "libnotify-bin" \
    --depends "network-manager" \
    --config-files /etc/kidlock/config.yaml \
    --before-install "$SCRIPT_DIR/debian/preinst" \
    --after-install "$SCRIPT_DIR/debian/postinst" \
    --before-remove "$SCRIPT_DIR/debian/prerm" \
    --after-remove "$SCRIPT_DIR/debian/postrm" \
    --package "$DIST_DIR/kidlock_${VERSION}_all.deb" \
    -C "$BUILD_DIR" \
    opt etc var

echo ""
echo "=== Build complete ==="
echo "Package: $DIST_DIR/kidlock_${VERSION}_all.deb"
echo ""
echo "Install with:"
echo "  sudo dpkg -i $DIST_DIR/kidlock_${VERSION}_all.deb"
echo "  sudo apt-get install -f  # if dependencies are missing"
echo ""
echo "Verify with:"
echo "  dpkg -I $DIST_DIR/kidlock_${VERSION}_all.deb"
echo "  dpkg -c $DIST_DIR/kidlock_${VERSION}_all.deb"
