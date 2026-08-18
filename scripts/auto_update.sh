#!/bin/bash
# Pull latest code from GitHub, rebuild Docker image, run one-off if triggered
set -eu
cd /opt/kontent-zavod
mkdir -p logs data
# Do not git-reset / rebuild while a run-once is in progress (avoids killing a long render)
if [ -f data/run-once.lock ] && ! flock -n data/run-once.lock true; then
  echo "$(date -Is) skip auto_update: run-once in progress" >> logs/update.log
  exit 0
fi
git fetch origin main
git reset --hard origin/main
sed -i 's/\r$//' scripts/*.sh
chmod +x scripts/*.sh
docker compose build worker
echo "$(date -Is) updated to $(git rev-parse --short HEAD)" >> logs/update.log
# Owner text/voice in Telegram → inbox/topic.txt + run-once
/opt/kontent-zavod/scripts/check_telegram_topic.sh || true
# New triggers/run-once.id (label run-now / Actions / merge) → one video to Telegram
/opt/kontent-zavod/scripts/check_run_once.sh || true
# New triggers/youtube-upload-once.id → upload newest output/*.mp4 as YouTube Short
/opt/kontent-zavod/scripts/check_youtube_upload.sh || true
# New triggers/telegram-story-once.id → post newest output/*.mp4 as Business story
/opt/kontent-zavod/scripts/check_telegram_story.sh || true
# New triggers/publish-once.id → multi-platform publish of newest output/*.mp4
/opt/kontent-zavod/scripts/check_publish_once.sh || true