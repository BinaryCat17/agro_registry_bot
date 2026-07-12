#!/bin/bash
# Sync agro_registry_bot source to the server, update deps, and restart.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="salskayastep"
REMOTE_DIR="/opt/agro_registry_bot"
SERVICE="agro-registry"

echo "==> Syncing source to server..."
rsync -az --delete --chown=root:root \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='data' \
  --exclude='logs' \
  --exclude='backups' \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  ./ "$HOST:$REMOTE_DIR/"

echo "==> Installing dependencies and restarting $SERVICE..."
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd "$REMOTE_DIR"
source .venv/bin/activate
pip install -q -r requirements.txt
systemctl restart $SERVICE
sleep 1
systemctl is-active --quiet $SERVICE && echo "$SERVICE is active" || (echo "$SERVICE FAILED to start"; exit 1)
EOF

echo "==> agro_registry_bot deployed."
