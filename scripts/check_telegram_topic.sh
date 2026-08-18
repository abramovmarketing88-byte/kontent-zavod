#!/bin/bash
# Poll Telegram for topic orders (text/voice) → inbox/topic.txt + run-once trigger.
set -eu
cd /opt/kontent-zavod
mkdir -p data logs inbox

if [ ! -f .env ]; then
  exit 0
fi
# shellcheck disable=SC1091
set -a
source .env
set +a

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_OWNER_CHAT_ID:-}" ]; then
  exit 0
fi
if [ "${TELEGRAM_TOPIC_INTAKE:-true}" = "false" ] || [ "${TELEGRAM_TOPIC_INTAKE:-true}" = "0" ]; then
  exit 0
fi

/usr/bin/docker compose run --rm worker python -m src.telegram.topic_intake \
  2>&1 | tee -a logs/telegram-topic.log
