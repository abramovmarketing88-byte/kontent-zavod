#!/bin/bash
# If triggers/publish-once.id changed, publish newest output/*.mp4 to all enabled platforms.
set -eu
cd /opt/kontent-zavod
TRIGGER_FILE=triggers/publish-once.id
STATE_FILE=data/last_publish_once.id
LOCK_FILE=data/publish-once.lock
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
  echo "$(date -Is) publish-once already running, skip id=$NEW_ID" >> logs/publish-once.log
  exit 0
fi

echo "$NEW_ID" > "$STATE_FILE"
echo "$(date -Is) publish-once start id=$NEW_ID" >> logs/publish-once.log

if /usr/bin/docker compose run --rm --no-deps worker \
  python -m src.publish.orchestrator >> logs/publish-once.log 2>&1; then
  echo "$(date -Is) publish-once done id=$NEW_ID" >> logs/publish-once.log
else
  echo "$(date -Is) publish-once FAILED id=$NEW_ID" >> logs/publish-once.log
  exit 1
fi
