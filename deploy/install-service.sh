#!/usr/bin/env bash
# Install the energy-router systemd service.
# Run with: sudo ./deploy/install-service.sh
set -euo pipefail

SERVICE_NAME="energy-router"
SERVICE_SRC="$(dirname "$0")/energy-router.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "ERROR: Service file not found at $SERVICE_SRC"
    echo "Run this script from the repository root."
    exit 1
fi

echo "==> Installing systemd service..."
sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload

echo "==> Enabling service (starts on boot)..."
sudo systemctl enable "$SERVICE_NAME"

echo "==> Starting service..."
sudo systemctl start "$SERVICE_NAME"

echo "==> Checking status..."
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Done! Manage with:"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "To configure the carbon API key, create /etc/energy-router.env:"
echo "  CARBON_API_KEY=your_electricitymap_api_key"
