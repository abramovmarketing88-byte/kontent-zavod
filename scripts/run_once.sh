#!/bin/bash
# One-off pipeline: discover viral Reels, render, send to Telegram DM
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed logs reports
TRIGGER_ID=""
if [ -f triggers/run-once.id ]; then
  TRIGGER_ID=$(tr -d '[:space:]' < triggers/run-once.id)
fi
export RUN_ONCE_TRIGGER_ID="${TRIGGER_ID}"

set +e
/usr/bin/docker compose run --rm \
  -e RUN_ONCE_TRIGGER_ID \
  -v /opt/kontent-zavod/reports:/app/reports \
  -v /opt/kontent-zavod/logs:/app/logs \
  worker python -m src.pipeline --once --notify-start \
  2>&1 | tee -a /opt/kontent-zavod/logs/pipeline.log | tee /opt/kontent-zavod/logs/pipeline.last.log
code=${PIPESTATUS[0]}
set -e

# Always try to publish the latest report (ok / empty / failed)
/opt/kontent-zavod/scripts/publish_run_report.sh || true
exit "$code"
