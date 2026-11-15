#!/bin/bash
# Publish «Северная Земля — 48 м²» under existing openresty docroot at /48/
# Does not replace the calculator on /.
set -eu
cd /opt/kontent-zavod
mkdir -p logs reports data

SITE_SRC=/opt/kontent-zavod/sites/severnaya-zemlya-48
LOG=logs/landing48.log
URL_FILE=reports/landing-48.url
log() { echo "$(date -Is) landing48-openresty: $*" | tee -a "$LOG"; }

if [ ! -f "$SITE_SRC/index.html" ]; then
  log "ERROR missing $SITE_SRC/index.html"
  exit 1
fi

HTML_ROOT=""
for p in \
  /usr/local/openresty/nginx/html \
  /usr/local/openresty/nginx/html/html \
  /var/www/html \
  /usr/share/nginx/html
do
  if [ -d "$p" ]; then
    HTML_ROOT=$p
    break
  fi
done

# Discover docroot from nginx/openresty config if needed
if [ -z "$HTML_ROOT" ]; then
  for conf in /usr/local/openresty/nginx/conf/nginx.conf /etc/nginx/nginx.conf; do
    if [ -f "$conf" ]; then
      root_guess=$(awk '/^\s*root\s+/ {print $2}' "$conf" | tr -d ';' | head -1 || true)
      if [ -n "${root_guess:-}" ] && [ -d "$root_guess" ]; then
        HTML_ROOT=$root_guess
        break
      fi
    fi
  done
fi

if [ -z "$HTML_ROOT" ]; then
  log "ERROR could not find openresty/nginx html root"
  ls -la /usr/local/openresty/nginx 2>&1 | tee -a "$LOG" || true
  ls -la /var/www 2>&1 | tee -a "$LOG" || true
  exit 1
fi

DEST="$HTML_ROOT/48"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$SITE_SRC"/. "$DEST"/
# Ensure readable by nginx worker
chmod -R a+rX "$DEST" || true
log "copied site to $DEST (docroot=$HTML_ROOT)"

# Keep LAN fallback on :8480
LANDING48_PORT=8480 /opt/kontent-zavod/scripts/serve_landing48.sh || true

PUB_IP=$(curl -4 -sS --connect-timeout 5 --max-time 10 https://ifconfig.me/ip 2>/dev/null \
  || curl -4 -sS --connect-timeout 5 --max-time 10 https://api.ipify.org 2>/dev/null || true)
PUB_IP=$(printf '%s' "$PUB_IP" | tr -d '[:space:]')
URL_PRIMARY="http://${PUB_IP}/48/"
URL_ALT="http://${PUB_IP}:8480/"
printf '%s\n' "$URL_PRIMARY" > "$URL_FILE"
{
  echo "url=$URL_PRIMARY"
  echo "url_alt=$URL_ALT"
  echo "public_ip=$PUB_IP"
  echo "dest=$DEST"
  echo "hostname=$(hostname 2>/dev/null || echo unknown)"
  echo "checked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > reports/landing-48.txt

code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "http://127.0.0.1/48/" || echo fail)
log "local /48/ -> $code"
if [ "$code" != "200" ]; then
  # Some setups need index explicitly
  code2=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "http://127.0.0.1/48/index.html" || echo fail)
  log "local /48/index.html -> $code2"
  ls -la "$DEST" | tee -a "$LOG" || true
fi

log "READY $URL_PRIMARY (alt $URL_ALT)"
echo "LANDING48_URL=$URL_PRIMARY"
echo "$URL_PRIMARY"

if [ -f .env ]; then
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  CHAT=$(grep -E '^TELEGRAM_OWNER_CHAT_ID=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  if [ -n "${TOKEN:-}" ] && [ -n "${CHAT:-}" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${CHAT}" \
      --data-urlencode "text=🏠 Лендинг 48 м²: ${URL_PRIMARY}" \
      >/dev/null 2>&1 || true
  fi
fi

if [ -x scripts/publish_landing48_report.sh ]; then
  scripts/publish_landing48_report.sh || true
fi
