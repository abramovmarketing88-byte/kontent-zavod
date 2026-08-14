#!/bin/bash
# If triggers/run-once.id changed since last run, fire a one-off pipeline.
set -eu
cd /opt/kontent-zavod
TRIGGER_FILE=triggers/run-once.id
STATE_FILE=data/last_run_once.id
mkdir -p data logs

if [ ! -f "$TRIGGER_FILE" ]; then
  exit 0
fi

NEW_ID=$(tr -d '[:space:]' < "$TRIGGER_FILE")
OLD_ID=""
if [ -f "$STATE_FILE" ]; then
  OLD_ID=$(tr -d '[:space:]' < "$STATE_FILE")
fi

if [ -z "$NEW_ID" ] || [ "$NEW_ID" = "$OLD_ID" ]; then
  exit 0
fi

echo "$(date -Is) run-once start id=$NEW_ID" >> logs/run-once.log
if /opt/kontent-zavod/scripts/run_once.sh; then
  echo "$NEW_ID" > "$STATE_FILE"
  echo "$(date -Is) run-once done id=$NEW_ID" >> logs/run-once.log
else
  echo "$(date -Is) run-once FAILED id=$NEW_ID" >> logs/run-once.log
  exit 1
fi
