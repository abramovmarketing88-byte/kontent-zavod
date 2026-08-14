#!/bin/bash
set -eu
cd /opt/kontent-zavod
timeout 20 docker compose run --rm worker 2>&1 | tee /tmp/scheduler_test.log || true
echo "timeout_exit=$?"
