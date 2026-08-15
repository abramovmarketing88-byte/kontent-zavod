#!/bin/bash
# If triggers/youtube-upload-once.id changed, upload newest output/*.mp4 as YouTube Short.
set -eu
cd /opt/kontent-zavod
TRIGGER_FILE=triggers/youtube-upload-once.id
STATE_FILE=data/last_youtube_upload.id
LOCK_FILE=data/youtube-upload.lock
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
  echo "$(date -Is) youtube-upload already running, skip id=$NEW_ID" >> logs/youtube-upload.log
  exit 0
fi

echo "$NEW_ID" > "$STATE_FILE"
echo "$(date -Is) youtube-upload start id=$NEW_ID" >> logs/youtube-upload.log

if /usr/bin/docker compose run --rm --no-deps worker \
  python -m src.publish.youtube >> logs/youtube-upload.log 2>&1; then
  echo "$(date -Is) youtube-upload done id=$NEW_ID" >> logs/youtube-upload.log
else
  echo "$(date -Is) youtube-upload FAILED id=$NEW_ID" >> logs/youtube-upload.log
  exit 1
fi
