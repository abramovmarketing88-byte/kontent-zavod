#!/bin/bash
# If triggers/telegram-story-once.id changed, post newest output/*.mp4 as Business story.
set -eu
cd /opt/kontent-zavod
TRIGGER_FILE=triggers/telegram-story-once.id
STATE_FILE=data/last_telegram_story.id
LOCK_FILE=data/telegram-story.lock
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
  echo "$(date -Is) telegram-story already running, skip id=$NEW_ID" >> logs/telegram-story.log
  exit 0
fi

echo "$NEW_ID" > "$STATE_FILE"
echo "$(date -Is) telegram-story start id=$NEW_ID" >> logs/telegram-story.log

if /usr/bin/docker compose run --rm --no-deps worker \
  python -m src.publish.telegram_story >> logs/telegram-story.log 2>&1; then
  echo "$(date -Is) telegram-story done id=$NEW_ID" >> logs/telegram-story.log
else
  echo "$(date -Is) telegram-story FAILED id=$NEW_ID" >> logs/telegram-story.log
  exit 1
fi
