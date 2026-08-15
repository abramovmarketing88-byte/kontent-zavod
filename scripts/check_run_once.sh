#!/bin/bash
# If triggers/run-once.id changed since last run, fire a one-off pipeline.
# Consume the trigger BEFORE starting so cron every 15m does not spam Telegram.
set -eu
cd /opt/kontent-zavod
TRIGGER_FILE=triggers/run-once.id
STATE_FILE=data/last_run_once.id
LOCK_FILE=data/run-once.lock
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

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) run-once already running, skip id=$NEW_ID" >> logs/run-once.log
  exit 0
fi

# Mark consumed immediately — failures need a NEW trigger id (Actions / label).
echo "$NEW_ID" > "$STATE_FILE"
echo "$(date -Is) run-once start id=$NEW_ID" >> logs/run-once.log

if /opt/kontent-zavod/scripts/run_once.sh; then
  echo "$(date -Is) run-once done id=$NEW_ID" >> logs/run-once.log
  /opt/kontent-zavod/scripts/diagnose.sh >> logs/diagnose.log 2>&1 || true
else
  echo "$(date -Is) run-once FAILED id=$NEW_ID" >> logs/run-once.log
  /opt/kontent-zavod/scripts/diagnose.sh >> logs/diagnose.log 2>&1 || true
  exit 1
fi
