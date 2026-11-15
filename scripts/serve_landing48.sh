#!/bin/bash
# Serve «Северная Земля — 48 м²» static landing on debian-home.
# Port: LANDING48_PORT (default 8480). Writes reports/landing-48.url
set -eu
cd /opt/kontent-zavod
mkdir -p logs reports data

SITE_DIR=/opt/kontent-zavod/sites/severnaya-zemlya-48
PORT="${LANDING48_PORT:-8480}"
PID_FILE=data/landing48.pid
LOG_FILE=logs/landing48.log
URL_FILE=reports/landing-48.url

if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "$(date -Is) landing48: missing $SITE_DIR/index.html" >> "$LOG_FILE"
  echo "missing site at $SITE_DIR" >&2
  exit 1
fi

already_up=0
if command -v ss >/dev/null 2>&1 && ss -lntp 2>/dev/null | grep -q ":${PORT} "; then
  already_up=1
elif command -v ss >/dev/null 2>&1 && ss -lntp 2>/dev/null | grep -q ":${PORT}\b"; then
  already_up=1
fi

if [ "$already_up" = "0" ]; then
  # Stop previous managed process if any
  if [ -f "$PID_FILE" ]; then
    old_pid=$(tr -d '[:space:]' < "$PID_FILE" || true)
    if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      sleep 0.5
    fi
    rm -f "$PID_FILE"
  fi

  # Best-effort firewall open (ignore failures)
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  fi

  nohup python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$SITE_DIR" \
    >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 0.8
  echo "$(date -Is) landing48: started pid=$(cat "$PID_FILE") port=$PORT" >> "$LOG_FILE"
else
  echo "$(date -Is) landing48: already listening on :$PORT" >> "$LOG_FILE"
fi

# Local health check
code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 \
  "http://127.0.0.1:${PORT}/" || echo fail)
if [ "$code" != "200" ]; then
  echo "$(date -Is) landing48: health check failed code=$code" >> "$LOG_FILE"
  echo "landing48 health check failed: $code" >&2
  exit 1
fi

PUB_IP=$(curl -4 -sS --connect-timeout 5 --max-time 10 https://ifconfig.me/ip 2>/dev/null \
  || curl -4 -sS --connect-timeout 5 --max-time 10 https://icanhazip.com 2>/dev/null \
  || curl -4 -sS --connect-timeout 5 --max-time 10 https://api.ipify.org 2>/dev/null \
  || true)
PUB_IP=$(echo "$PUB_IP" | tr -d '[:space:]')

if [ -z "$PUB_IP" ]; then
  PUB_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi

URL="http://${PUB_IP}:${PORT}/"
printf '%s\n' "$URL" > "$URL_FILE"
{
  echo "url=$URL"
  echo "port=$PORT"
  echo "public_ip=$PUB_IP"
  echo "hostname=$(hostname 2>/dev/null || echo unknown)"
  echo "checked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "http_local=$code"
} > reports/landing-48.txt

echo "$URL"

# Notify owner via Telegram when configured
if [ -f .env ]; then
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  CHAT=$(grep -E '^TELEGRAM_OWNER_CHAT_ID=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  if [ -n "${TOKEN:-}" ] && [ -n "${CHAT:-}" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${CHAT}" \
      --data-urlencode "text=🏠 Лендинг 48 м² на debian-home:${URL}" \
      >/dev/null 2>&1 || true
  fi
fi

# Publish URL into run-reports branch when possible
if [ -x scripts/publish_landing48_report.sh ]; then
  scripts/publish_landing48_report.sh || true
fi
