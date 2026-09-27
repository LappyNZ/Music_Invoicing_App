#!/bin/bash
# Update the app to the newest published version, taking a backup first.
#
#   bash update.sh
#
# To go back to an earlier version, see "Rolling back" in README.md.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/mnt/user/appdata/music-invoice}"
CONTAINER="${CONTAINER:-music-invoice}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

# Use the same compose file and project the container was started with, so compose updates
# it rather than trying to create a second container with the same name.
label() { docker inspect -f "{{ index .Config.Labels \"$1\" }}" "$CONTAINER" 2>/dev/null || true; }
compose=(docker compose -f "$APP_DIR/docker-compose.prod.yml")
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  started_from=$(label com.docker.compose.project.config_files)
  case "$started_from" in
    */music-invoice/docker-compose.prod.yml) ;;
    "")
      echo "The $CONTAINER container wasn't started with docker compose, so this script can't update it." >&2
      exit 1 ;;
    *)
      echo "The $CONTAINER container was started from $started_from," >&2
      echo "not $APP_DIR/docker-compose.prod.yml. Update it the way it was started, or ask for help." >&2
      exit 1 ;;
  esac
  compose+=(-p "$(label com.docker.compose.project)")
fi

echo "== 1/4 Backing up"
bash "$HERE/backup.sh"

echo "== 2/4 Downloading the newest version"
"${compose[@]}" pull

echo "== 3/4 Restarting with it"
"${compose[@]}" up -d

echo "== 4/4 Waiting for it to report healthy (up to 2 minutes)"
status=unknown
for _ in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo unknown)
  [ "$status" = "healthy" ] && break
  sleep 2
done
version=$(docker exec "$CONTAINER" printenv APP_VERSION 2>/dev/null || echo unknown)
if [ "$status" = "healthy" ]; then
  echo "OK: the app is running version ${version:0:7}"
else
  echo "WARNING: the container reports '$status'. See what went wrong with: docker logs $CONTAINER" >&2
  exit 1
fi
