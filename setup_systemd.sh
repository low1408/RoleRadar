#!/usr/bin/env bash
# setup_systemd.sh
#
# Generates and installs systemd user unit files to run scheduled_ingest.sh
# daily at 06:00, with boot-persistent catch-up triggering.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

echo "Using project directory: $ROOT_DIR"
echo "Installing to user systemd directory: $SYSTEMD_DIR"

# Generate roleradar-ingest.service
cat <<EOF > "$SYSTEMD_DIR/roleradar-ingest.service"
[Unit]
Description=RoleRadar Job Ingestion Service
After=network.target

[Service]
Type=oneshot
ExecStart=$ROOT_DIR/scheduled_ingest.sh
WorkingDirectory=$ROOT_DIR
StandardOutput=append:$ROOT_DIR/scheduled_ingest.log
StandardError=append:$ROOT_DIR/scheduled_ingest.log
EOF

# Generate roleradar-ingest.timer
cat <<EOF > "$SYSTEMD_DIR/roleradar-ingest.timer"
[Unit]
Description=Run RoleRadar Job Ingestion daily and on boot if missed

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "Systemd user service and timer generated successfully."

# Reload systemd configuration for the user session
systemctl --user daemon-reload

# Enable and start the timer
systemctl --user enable roleradar-ingest.timer
systemctl --user start roleradar-ingest.timer

echo ""
echo "=========================================================================="
echo "SUCCESS: RoleRadar systemd timer has been installed and started!"
echo "=========================================================================="
echo "Next run: $(systemctl --user list-timers roleradar-ingest.timer | grep roleradar-ingest || true)"
echo ""
echo "To check service status: systemctl --user status roleradar-ingest"
echo "To run ingestion manually right now: systemctl --user start roleradar-ingest"
echo "To view logs: tail -f $ROOT_DIR/scheduled_ingest.log"
echo "=========================================================================="
