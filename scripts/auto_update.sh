#!/bin/bash
# Pull latest code from GitHub, rebuild Docker image, run one-off if triggered
set -eu
cd /opt/kontent-zavod
mkdir -p logs
git fetch origin main
git reset --hard origin/main
sed -i 's/\r$//' scripts/*.sh
chmod +x scripts/*.sh
docker compose build worker
echo "$(date -Is) updated to $(git rev-parse --short HEAD)" >> logs/update.log
# New triggers/run-once.id (label run-now / Actions / merge) → one video to Telegram
/opt/kontent-zavod/scripts/check_run_once.sh || true
