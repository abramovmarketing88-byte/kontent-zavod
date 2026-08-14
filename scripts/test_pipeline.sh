#!/bin/bash
set -eu
cd /opt/kontent-zavod
docker run --rm --env-file /opt/kontent-zavod/.env \
  -v /opt/kontent-zavod/output:/app/output \
  -v /opt/kontent-zavod/jobs:/app/jobs \
  -v /opt/kontent-zavod/data:/app/data \
  -v /opt/kontent-zavod/inbox:/app/inbox \
  -v /opt/kontent-zavod/brand:/app/brand \
  -v /opt/kontent-zavod/config:/app/config \
  kontent-zavod-worker python -m src.pipeline --once 2>&1 | tee /tmp/pipeline_test.log
echo "pipeline_exit=$?"
