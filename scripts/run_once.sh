#!/bin/bash
# One-off pipeline: discover viral Reels, render, send to Telegram DM
set -eu
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed logs
/usr/bin/docker compose run --rm worker python -m src.pipeline --once --notify-start \
  >> /opt/kontent-zavod/logs/pipeline.log 2>&1
