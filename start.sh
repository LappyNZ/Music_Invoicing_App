#!/usr/bin/env bash
set -e

: "${APP_MODULE:=app:app}"
: "${PORT:=8000}"
: "${WORKERS:=3}"
: "${TIMEOUT:=60}"

echo "Starting Flask app with APP_MODULE=${APP_MODULE} on PORT=${PORT}"

exec gunicorn "$APP_MODULE" \
  --bind 0.0.0.0:"$PORT" \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT"