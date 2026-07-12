#!/bin/bash
# ===========================================================
# StudyGuide DB Backup Script
# Backs up the SQLite database safely (WAL-aware) with rotation.
# Add to crontab:  0 */6 * * * /home/ubuntu/studyguide/backup.sh
# ===========================================================

APP_DIR="/home/ubuntu/studyguide"
DB_FILE="$APP_DIR/studyguide.db"
BACKUP_DIR="$APP_DIR/backups"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DEST="$BACKUP_DIR/studyguide_$TIMESTAMP.db"

# Use sqlite3 .backup for a consistent copy (handles WAL correctly)
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_FILE" ".backup '$DEST'"
else
    # Fallback: plain copy (install sqlite3 for safest backups)
    cp "$DB_FILE" "$DEST"
fi

# Compress
gzip -f "$DEST"

# Delete backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "*.db.gz" -mtime +$KEEP_DAYS -delete

echo "$(date): Backup created -> $DEST.gz"