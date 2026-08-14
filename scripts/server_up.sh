#!/bin/bash
set -eu
cd /opt/kontent-zavod
mkdir -p output jobs data inbox/processed
docker compose down 2>/dev/null || true
docker compose up -d --build
sleep 8
docker compose ps
docker compose logs --tail 40 worker
