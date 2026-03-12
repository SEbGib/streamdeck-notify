#!/bin/bash
set -euo pipefail

echo "=== Stream Deck Notify — Setup ==="

# 1. Udev rules (needs sudo)
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
if [ ! -f "$UDEV_RULE" ]; then
    echo "[1/4] Installing udev rules..."
    echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"' | sudo tee "$UDEV_RULE"
    sudo udevadm control --reload-rules
    echo "  → Replug your Stream Deck for rules to take effect."
else
    echo "[1/4] Udev rules already installed."
fi

# 2. System dependencies
echo "[2/4] Installing system dependencies..."
sudo apt-get install -y --no-install-recommends \
    libudev-dev libusb-1.0-0-dev libhidapi-libusb0 \
    libjpeg-dev zlib1g-dev python3-venv

# 3. Python venv & dependencies
echo "[3/4] Setting up Python environment..."
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 4. Config directory
echo "[4/4] Creating config directory..."
mkdir -p ~/.config/streamdeck-notify

echo ""
echo "=== Setup complete ==="
echo ""
echo "To run:  source .venv/bin/activate && streamdeck-notify"
echo "To install as service: systemctl --user enable --now streamdeck-notify"
