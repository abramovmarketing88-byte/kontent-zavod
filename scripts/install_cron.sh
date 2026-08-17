#!/bin/bash
set -eu
cd /opt/kontent-zavod
sed -i 's/\r$//' scripts/daily_run.sh
chmod +x scripts/daily_run.sh
docker compose build worker
CRON_LINE="0 9 * * * /opt/kontent-zavod/scripts/daily_run.sh"
UPDATE_LINE="*/5 * * * * /opt/kontent-zavod/scripts/auto_update.sh"
(crontab -l 2>/dev/null | grep -v kontent-zavod; echo "$CRON_LINE"; echo "$UPDATE_LINE") | crontab -
echo "Cron installed:"
crontab -l | grep kontent
docker compose down 2>/dev/null || true
