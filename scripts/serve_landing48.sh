#!/bin/bash
# Serve «Северная Земля — 48 м²» static landing on debian-home.
# Port: LANDING48_PORT (default 8480). Writes reports/landing-48.url
set -eu
cd /opt/kontent-zavod
mkdir -p logs reports data

SITE_DIR=/opt/kontent-zavod/sites/severnaya-zemlya-48
# Prefer 80 for WAN (home routers often forward HTTP); override with LANDING48_PORT.
PORT="${LANDING48_PORT:-8480}"
PID_FILE=data/landing48.pid
LOG_FILE=logs/landing48.log
URL_FILE=reports/landing-48.url

log() { echo "$(date -Is) landing48: $*" | tee -a "$LOG_FILE"; }

if [ ! -f "$SITE_DIR/index.html" ]; then
  log "ERROR missing $SITE_DIR/index.html"
  ls -la /opt/kontent-zavod/sites 2>&1 | tee -a "$LOG_FILE" || true
  exit 1
fi

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  log "ERROR python3/python not found"
  exit 1
fi

listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -lntp 2>/dev/null | grep -E ":${PORT}\\b" >/dev/null 2>&1
  elif command -v netstat >/dev/null 2>&1; then
    netstat -lntp 2>/dev/null | grep -E ":${PORT}\\b" >/dev/null 2>&1
  else
    return 1
  fi
}

if listening; then
  log "already listening on :$PORT"
else
  if [ -f "$PID_FILE" ]; then
    old_pid=$(tr -d '[:space:]' < "$PID_FILE" || true)
    if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      sleep 0.5
    fi
    rm -f "$PID_FILE"
  fi

  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
    ufw allow 8480/tcp >/dev/null 2>&1 || true
  fi
  if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null || true
  fi

  # If preferred port is busy, fall back to 8480
  if [ "$PORT" = "80" ] && listening; then
    log "port 80 already in use, falling back to 8480"
    PORT=8480
    PID_FILE=data/landing48.pid
  fi

  nohup "$PY" -m http.server "$PORT" --bind 0.0.0.0 --directory "$SITE_DIR" \
    >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.4
    if listening; then
      break
    fi
  done
  log "started pid=$(tr -d '[:space:]' < "$PID_FILE") port=$PORT py=$PY"
fi

code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 \
  "http://127.0.0.1:${PORT}/" || echo fail)
if [ "$code" != "200" ]; then
  log "ERROR health check failed code=$code"
  tail -n 30 "$LOG_FILE" || true
  exit 1
fi

PUB_IP=$(curl -4 -sS --connect-timeout 5 --max-time 10 https://ifconfig.me/ip 2>/dev/null \
  || curl -4 -sS --connect-timeout 5 --max-time 10 https://icanhazip.com 2>/dev/null \
  || curl -4 -sS --connect-timeout 5 --max-time 10 https://api.ipify.org 2>/dev/null \
  || true)
PUB_IP=$(printf '%s' "$PUB_IP" | tr -d '[:space:]')
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

log "READY $URL"
echo "LANDING48_URL=$URL"
echo "$URL"

# Notify owner via Telegram when configured
if [ -f .env ]; then
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  CHAT=$(grep -E '^TELEGRAM_OWNER_CHAT_ID=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  if [ -n "${TOKEN:-}" ] && [ -n "${CHAT:-}" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${CHAT}" \
      --data-urlencode "text=🏠 Лендинг 48 м² на debian-home: ${URL}" \
      >/dev/null 2>&1 || true
  fi
fi

if [ -x scripts/publish_landing48_report.sh ]; then
  scripts/publish_landing48_report.sh || true
fi
