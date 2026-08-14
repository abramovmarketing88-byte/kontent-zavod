#!/bin/bash
# One-off pipeline: discover viral Reels, render, send to Telegram DM
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed logs
# Keep last run readable for diagnose; full history in pipeline.log
/usr/bin/docker compose run --rm worker python -m src.pipeline --once --notify-start \
  2>&1 | tee -a /opt/kontent-zavod/logs/pipeline.log | tee /opt/kontent-zavod/logs/pipeline.last.log
