#!/bin/bash
# One-off tidy of the app folder on Unraid. Moves files the current setup doesn't use into
# old-YYYYMMDD/ (nothing is deleted) and installs the updated docker-compose.prod.yml.
#
#   bash tidy-server.sh           # dry run: shows what it would do, changes nothing
#   bash tidy-server.sh --apply   # does it
#
# The running app isn't affected; the new compose file takes effect at the next update.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/mnt/user/appdata/music-invoice}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ARCHIVE="old-$(date +%Y%m%d)"
APPLY=false
if [ "${1:-}" = "--apply" ]; then APPLY=true; fi

if [ ! -f "$HERE/docker-compose.prod.yml" ]; then
  echo "Put the updated docker-compose.prod.yml next to this script first; stopping." >&2
  exit 1
fi
cd "$APP_DIR"
if [ ! -f .env.prod ] || [ ! -d data ] || [ ! -d secrets ] || [ ! -f docker-compose.prod.yml ]; then
  echo "$APP_DIR doesn't look like the app folder; stopping." >&2
  exit 1
fi
if ! grep -q "image: ghcr.io/lappynz/music_invoicing_app" docker-compose.prod.yml; then
  echo "docker-compose.prod.yml doesn't run the GitHub image, so the old build files may still be in use; stopping." >&2
  exit 1
fi

archive() {
  if $APPLY; then
    mkdir -p "$ARCHIVE/$(dirname "$1")"
    mv "$1" "$ARCHIVE/$1"
    echo "  moved $1"
  else
    echo "  would move $1"
  fi
}

$APPLY || echo "Dry run: nothing will change. Run again with --apply to do it."
echo "Into $APP_DIR/$ARCHIVE:"

# Leftovers from the old "build from this folder" setup (the app now comes from the GitHub image)
for item in app Dockerfile docker-compose.yml start.sh certs; do
  if [ -e "$item" ]; then archive "$item"; fi
done
# Old copies of the database from October 2025 (the nightly backups replace these)
for item in data/music_school.db.BAK.* data/music_school.db.PRE-MERGE.*; do
  if [ -e "$item" ]; then archive "$item"; fi
done

# The updated compose file sets TZ and PORT itself, so the old one's .env helper isn't needed.
if ! cmp -s "$HERE/docker-compose.prod.yml" docker-compose.prod.yml; then
  archive docker-compose.prod.yml
  if $APPLY; then
    cp "$HERE/docker-compose.prod.yml" docker-compose.prod.yml
    echo "  installed the updated docker-compose.prod.yml"
  else
    echo "  would install the updated docker-compose.prod.yml"
  fi
fi
if [ -e .env ]; then archive .env; fi

if $APPLY; then
  echo "Done. Kept in place: data/, secrets/, .env.prod, docker-compose.prod.yml, scripts/."
  echo "Once everything has worked for a few weeks you can delete $APP_DIR/$ARCHIVE."
fi
