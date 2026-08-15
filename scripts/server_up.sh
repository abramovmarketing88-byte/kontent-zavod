#!/bin/bash
set -eu
cd /opt/kontent-zavod
# shellcheck disable=SC1091
[ -x scripts/show_author.sh ] && bash scripts/show_author.sh || true
mkdir -p output jobs data inbox/processed
docker compose down 2>/dev/null || true
docker compose up -d --build
sleep 8
docker compose ps
docker compose logs --tail 40 worker
echo "Готово. Канал: https://t.me/Abramov_like · вопросы: https://t.me/Abramow191"
