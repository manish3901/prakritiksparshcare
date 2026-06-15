#!/usr/bin/env bash
set -eu

# Hourly PSC web watchdog.
# If psc_web stays down for 1 hour, bring it back up.

cd /opt/psc || exit 1

STATE_FILE="/var/tmp/psc_web_down_since"
SERVICE_NAME="psc_web"
THRESHOLD_SECONDS=3600

if docker inspect -f '{{.State.Running}}' "$SERVICE_NAME" 2>/dev/null | grep -q true; then
  rm -f "$STATE_FILE"
  exit 0
fi

now="$(date +%s)"

if [ ! -f "$STATE_FILE" ]; then
  printf '%s\n' "$now" > "$STATE_FILE"
  exit 0
fi

down_since="$(cat "$STATE_FILE" 2>/dev/null || echo "$now")"
elapsed=$((now - down_since))

if [ "$elapsed" -ge "$THRESHOLD_SECONDS" ]; then
  docker compose up -d "$SERVICE_NAME"
  rm -f "$STATE_FILE"
fi
