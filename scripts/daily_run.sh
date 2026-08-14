#!/bin/bash
# Daily pipeline: generate 1 Reels + send to Telegram DM
set -eu
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed logs
/usr/bin/docker compose run --rm worker python -m src.pipeline --once \
  >> /opt/kontent-zavod/logs/pipeline.log 2>&1
