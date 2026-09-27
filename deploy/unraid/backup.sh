#!/bin/bash
# Back up the music invoicing app: database, invoice PDFs, settings and Gmail credentials.
#
# Run nightly from the Unraid "User Scripts" plugin, or by hand:  bash backup.sh
# Each run writes one dated archive to $DEST/daily, kept for $KEEP_DAILY days. The one made on
# the 1st of the month is also copied to $DEST/monthly and kept for $KEEP_MONTHLY months.
# The archives hold the Gmail token and bank details, so they are readable by root only.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/mnt/user/appdata/music-invoice}"
DEST="${DEST:-/mnt/user/backups/music-invoice}"
CONTAINER="${CONTAINER:-music-invoice}"
KEEP_DAILY=30
KEEP_MONTHLY=24

notify() {  # shows in the Unraid web UI, and by email/phone if Unraid notifications are set up
  local unraid_notify=/usr/local/emhttp/webGui/scripts/notify
  if [ -x "$unraid_notify" ]; then
    "$unraid_notify" -e "Music invoice backup" -s "$2" -i "$1" >/dev/null 2>&1 || true
  fi
}
fail() {
  echo "BACKUP FAILED: $*" >&2
  notify alert "Backup failed: $*"
  exit 1
}
trap 'fail "unexpected error on line $LINENO (see the script log)"' ERR

[ -f "$APP_DIR/.env.prod" ] && [ -f "$APP_DIR/data/music_school.db" ] \
  || fail "$APP_DIR doesn't look like the app folder (no .env.prod or data/music_school.db)"

mkdir -p "$DEST/daily" "$DEST/monthly"
chmod 700 "$DEST"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
stamp=$(date +%Y-%m-%d_%H%M)

# 1. A consistent copy of the database
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; then
  # SQLite's online backup, run inside the container so it can't catch a half-written change.
  docker exec -i "$CONTAINER" python - <<'PY'
import os, sqlite3
db = os.environ.get("DB_PATH", "/data/music_school.db")
out = os.path.join(os.path.dirname(db), ".backup-in-progress.db")
if os.path.exists(out):
    os.remove(out)
src, dst = sqlite3.connect(db), sqlite3.connect(out)
src.backup(dst)
src.close()
result = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close()
if result != "ok":
    raise SystemExit(f"database integrity check failed: {result}")
PY
  mv "$APP_DIR/data/.backup-in-progress.db" "$work/music_school.db"
else
  echo "The $CONTAINER container isn't running, so copying the database file as it is."
  cp "$APP_DIR/data/music_school.db" "$work/music_school.db"
fi

# 2. One archive with everything needed to rebuild the app on another server
items=()
for item in data/invoices_pdfs secrets .env.prod docker-compose.prod.yml .env; do
  if [ -e "$APP_DIR/$item" ]; then items+=("$item"); fi
done
archive="$DEST/daily/music-invoice_$stamp.tar.gz"
tar -czf "$archive.partial" -C "$work" music_school.db -C "$APP_DIR" "${items[@]}"
tar -tzf "$archive.partial" >/dev/null
mv "$archive.partial" "$archive"
chmod 600 "$archive"

# 3. Keep a monthly copy, and clear out old ones
if [ "$(date +%d)" = "01" ]; then
  cp -p "$archive" "$DEST/monthly/"
fi
find "$DEST/daily" -name 'music-invoice_*.tar.gz' -mtime +"$KEEP_DAILY" -delete
find "$DEST/monthly" -name 'music-invoice_*.tar.gz' -mtime +$((KEEP_MONTHLY * 31)) -delete

count() { find "$1" -name 'music-invoice_*.tar.gz' | wc -l; }
echo "Backup OK: $archive ($(du -h "$archive" | cut -f1)); $(count "$DEST/daily") daily and $(count "$DEST/monthly") monthly backups kept."
