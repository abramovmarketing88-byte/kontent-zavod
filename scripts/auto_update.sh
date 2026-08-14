#!/bin/bash
# Pull latest code from GitHub and rebuild Docker image
set -eu
cd /opt/kontent-zavod
git fetch origin main
git reset --hard origin/main
sed -i 's/\r$//' scripts/*.sh
chmod +x scripts/*.sh
docker compose build worker
echo "$(date -Is) updated to $(git rev-parse --short HEAD)" >> logs/update.log
