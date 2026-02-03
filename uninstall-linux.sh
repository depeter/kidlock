#!/bin/bash
# Kidlock Linux uninstaller
# Must be run with sudo

set -e

echo "=== Kidlock Linux Uninstaller ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "This uninstaller must be run as root (with sudo)."
    echo "Usage: sudo ./uninstall-linux.sh"
    exit 1
fi

read -p "This will completely remove Kidlock. Continue? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Stop and disable service
echo "Stopping service..."
systemctl stop kidlock 2>/dev/null || true
systemctl disable kidlock 2>/dev/null || true

# Remove systemd service
echo "Removing systemd service..."
rm -f /etc/systemd/system/kidlock.service
systemctl daemon-reload

# Remove PAM integration
echo "Removing PAM integration..."
for pam_file in /etc/pam.d/common-auth /etc/pam.d/login /etc/pam.d/gdm-password /etc/pam.d/lightdm; do
    if [ -f "$pam_file" ]; then
        sed -i '/kidlock-pam-check/d' "$pam_file"
    fi
done

# Remove PAM check script
rm -f /usr/local/bin/kidlock-pam-check

# Remove dnsmasq config
echo "Removing DNS config..."
rm -f /etc/NetworkManager/dnsmasq.d/kidlock.conf
rm -f /etc/NetworkManager/conf.d/kidlock-dns.conf
systemctl restart NetworkManager 2>/dev/null || true

# Remove installation directory
echo "Removing installation directory..."
rm -rf /opt/kidlock

# Remove state directory
echo "Removing state directory..."
rm -rf /var/lib/kidlock

# Ask about config
echo ""
read -p "Remove config (/etc/kidlock)? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf /etc/kidlock
    echo "Config removed."
else
    echo "Config preserved at /etc/kidlock"
fi

echo ""
echo "=== Uninstall Complete ==="
echo "Kidlock has been removed from this system."
