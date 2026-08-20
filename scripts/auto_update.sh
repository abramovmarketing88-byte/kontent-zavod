#!/bin/bash
# Pull latest code from GitHub onto debian-home, rebuild Docker if commit changed.
set -eu
cd /opt/kontent-zavod
mkdir -p logs data

if [ -f data/run-once.lock ] && ! flock -n data/run-once.lock true; then
  echo "$(date -Is) skip auto_update: run-once in progress" >> logs/update.log
  exit 0
fi

git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
  git reset --hard origin/main
  sed -i 's/\r$//' scripts/*.sh
  chmod +x scripts/*.sh
  docker compose build worker
  echo "$(date -Is) updated to $(git rev-parse --short HEAD)" >> logs/update.log
else
  echo "$(date -Is) already $(git rev-parse --short HEAD)" >> logs/update.log
fi

/opt/kontent-zavod/scripts/check_telegram_topic.sh || true
/opt/kontent-zavod/scripts/check_run_once.sh || true
/opt/kontent-zavod/scripts/check_youtube_upload.sh || true
/opt/kontent-zavod/scripts/check_telegram_story.sh || true
/opt/kontent-zavod/scripts/check_publish_once.sh || true
