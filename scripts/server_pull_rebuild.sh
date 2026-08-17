#!/bin/bash
set -eu
cd /opt/kontent-zavod
git fetch origin main
git reset --hard origin/main
sed -i 's/\r$//' scripts/*.sh 2>/dev/null || true
docker compose build worker
echo "commit=$(git rev-parse --short HEAD)"
docker compose run --rm worker python -c 'from src.analyze.transcriber import transcribe_audio; print("transcriber ok")'
echo UPDATE_OK
