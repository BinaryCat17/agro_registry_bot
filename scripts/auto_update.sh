#!/bin/bash
# Auto-update script for agro registry database
# Run this via cron at midnight: 0 0 * * * /path/to/scripts/auto_update.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$PROJECT_DIR/backups"
LOG_FILE="$PROJECT_DIR/auto_update.log"

# Create backup dir if needed
mkdir -p "$BACKUP_DIR"

# Timestamp for backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "========================================" >> "$LOG_FILE"
echo "[$(date)] Starting auto-update..." >> "$LOG_FILE"

# Backup current DB before update
if [ -f "$DATA_DIR/reestr.db" ]; then
    echo "[$(date)] Backing up database..." >> "$LOG_FILE"
    cp "$DATA_DIR/reestr.db" "$BACKUP_DIR/reestr_backup_$TIMESTAMP.db"
    # Keep only last 10 backups
    ls -t "$BACKUP_DIR"/reestr_backup_*.db | tail -n +11 | xargs -r rm
fi

# Activate venv and run update
cd "$PROJECT_DIR"
source .venv/bin/activate

echo "[$(date)] Downloading and importing XML data..." >> "$LOG_FILE"
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
from src.importer import run_import
try:
    run_import()
    print('IMPORT_SUCCESS')
except Exception as e:
    print(f'IMPORT_FAILED: {e}')
    sys.exit(1)
" >> "$LOG_FILE" 2>&1

if [ $? -ne 0 ]; then
    echo "[$(date)] ❌ Import failed!" >> "$LOG_FILE"
    exit 1
fi

echo "[$(date)] Running classification scripts..." >> "$LOG_FILE"

# Rebuild crops from new data
python3 "$SCRIPT_DIR/rebuild_crops.py" >> "$LOG_FILE" 2>&1 || true

# Classify all products
python3 "$SCRIPT_DIR/classify.py" >> "$LOG_FILE" 2>&1 || true

# Classify crop groups
python3 "$SCRIPT_DIR/classify_crop_groups.py" >> "$LOG_FILE" 2>&1 || true

echo "[$(date)] ✅ Auto-update completed!" >> "$LOG_FILE"

# Restart web server (optional - uncomment if needed)
# pkill -f "python3 web/main.py" || true
# sleep 2
# nohup python3 "$PROJECT_DIR/web/main.py" > "$PROJECT_DIR/web.log" 2>&1 &
echo "[$(date)] Web server restart skipped (manual restart required)" >> "$LOG_FILE"
