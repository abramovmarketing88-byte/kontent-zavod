#!/bin/bash
# Daily pipeline: generate 1 Reels + send to Telegram DM
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed logs reports
set +e
/usr/bin/docker compose run --rm worker python -m src.pipeline --once \
  >> /opt/kontent-zavod/logs/pipeline.log 2>&1
code=$?
set -e
/opt/kontent-zavod/scripts/publish_run_report.sh || true
exit "$code"
