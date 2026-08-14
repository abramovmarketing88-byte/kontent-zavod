#!/bin/bash
# Generate hybrid reel and send to Telegram DM (via mihomo VPN proxy)
set -eu
cd /opt/kontent-zavod
mkdir -p logs output jobs data inbox/processed

/usr/bin/docker compose run --rm worker python -m src.render_job content-factory-launch \
  --renderer hybrid --refresh-shots --suffix server-v1 --publish \
  >> logs/render.log 2>&1

echo "$(date -Is) render done" >> logs/render.log
