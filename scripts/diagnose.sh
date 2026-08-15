#!/bin/bash
# Host-side diagnostics for Kontent Zavod. Writes reports/diagnose.md (no secrets)
# and optionally sends it to Telegram.
set -euo pipefail
ROOT="${PROJECT_ROOT:-/opt/kontent-zavod}"
cd "$ROOT"
mkdir -p reports logs data

OUT=reports/diagnose.md
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

redact() {
  sed -E \
    -e 's/[Aa][Ii]za[0-9A-Za-z_-]+/***/g' \
    -e 's/bot[0-9]+:[A-Za-z0-9_-]+/bot***/g' \
    -e 's/(key=)[^&\s]+/\1***/g' \
    -e 's/(TOKEN|API_KEY|PASSWORD|SECRET)=.*/\1=***/g' \
    -e 's/sk-[A-Za-z0-9_-]{8,}/***/g' \
    -e 's/sk_or_v1_[A-Za-z0-9_-]+/***/g'
}

{
  echo "# Diagnose report \`$TS\`"
  echo
  echo "## Host"
  echo "- hostname: \`$(hostname 2>/dev/null || echo unknown)\`"
  echo "- pwd: \`$ROOT\`"
  echo "- git: \`$(git rev-parse --short HEAD 2>/dev/null || echo none)\` ($(git log -1 --pretty=%s 2>/dev/null || echo n/a))"
  echo

  echo "## Proxy :7890"
  if command -v ss >/dev/null 2>&1 && ss -lntp 2>/dev/null | grep -q ':7890'; then
    echo "- listener: **YES**"
  elif command -v netstat >/dev/null 2>&1 && netstat -lntp 2>/dev/null | grep -q ':7890'; then
    echo "- listener: **YES**"
  else
    echo "- listener: **NO**"
  fi
  for url in https://www.youtube.com https://api.telegram.org https://www.googleapis.com; do
    code_direct=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 8 --max-time 15 "$url" 2>/dev/null || echo fail)
    code_proxy=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 8 --max-time 15 -x http://127.0.0.1:7890 "$url" 2>/dev/null || echo fail)
    echo "- \`$url\` direct=\`$code_direct\` via_proxy=\`$code_proxy\`"
  done
  echo

  echo "## Cron / triggers"
  echo '```'
  (crontab -l 2>/dev/null | grep -E 'kontent|daily_run|auto_update|run_once' || echo '(no matching crontab)')
  echo '```'
  echo "- trigger: \`$(tr -d '[:space:]' < triggers/run-once.id 2>/dev/null || echo missing)\`"
  echo "- last_run_once: \`$(tr -d '[:space:]' < data/last_run_once.id 2>/dev/null || echo missing)\`"
  if [ -f data/run-once.lock ]; then
    if flock -n data/run-once.lock true 2>/dev/null; then
      echo "- run-once.lock: **free**"
    else
      echo "- run-once.lock: **HELD**"
    fi
  else
    echo "- run-once.lock: missing"
  fi
  echo
  echo "### update.log (tail)"
  echo '```'
  tail -n 20 logs/update.log 2>/dev/null || echo '(empty)'
  echo '```'
  echo
  echo "### run-once.log (tail)"
  echo '```'
  tail -n 30 logs/run-once.log 2>/dev/null || echo '(empty)'
  echo '```'
  echo

  echo "## Env flags (presence only)"
  if [ -f .env ]; then
    for key in CURSOR_API_KEY ELEVENLABS_API_KEY YOUTUBE_API_KEY PEXELS_API_KEY \
      OPENROUTER_API_KEY OPENAI_API_KEY HEYGEN_API_KEY HEYGEN_AVATAR_ID \
      TELEGRAM_BOT_TOKEN TELEGRAM_OWNER_CHAT_ID TELEGRAM_NOTIFY RENDERER \
      TRANSCRIBE_BACKEND IG_USERNAME IG_SESSION_FILE PROXY_REQUIRED \
      HTTP_PROXY HTTPS_PROXY YTDLP_COOKIES_FILE; do
      if grep -Eq "^${key}=.+" .env 2>/dev/null; then
        val=$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2- | tr -d '\r')
        # show non-secret values fully; secrets as set/empty
        case "$key" in
          TELEGRAM_NOTIFY|RENDERER|TRANSCRIBE_BACKEND|PROXY_REQUIRED|HTTP_PROXY|HTTPS_PROXY)
            echo "- \`$key\`=\`$val\`"
            ;;
          *)
            echo "- \`$key\`=**set**"
            ;;
        esac
      else
        echo "- \`$key\`=missing"
      fi
    done
  else
    echo "- .env **missing**"
  fi
  echo

  echo "## docker-compose proxy block"
  echo '```'
  grep -E 'PROXY|proxy' docker-compose.yml 2>/dev/null || echo '(none)'
  echo '```'
  echo

  echo "## SQLite sources"
  if [ -f data/factory.db ]; then
    echo '```'
    sqlite3 data/factory.db "SELECT status, COUNT(*) FROM sources GROUP BY status ORDER BY 1;" 2>/dev/null || echo 'sqlite3 failed'
    echo '```'
    echo
    echo "### last 15"
    echo '```'
    sqlite3 -header -column data/factory.db \
      "SELECT source_id, status, substr(COALESCE(error,''),1,60) AS err, updated_at FROM sources ORDER BY updated_at DESC LIMIT 15;" \
      2>/dev/null || echo 'query failed'
    echo '```'
  else
    echo "- data/factory.db missing"
  fi
  echo

  echo "## Last run report"
  if [ -f reports/last-run.md ]; then
    echo
    # include body but redact again
    redact < reports/last-run.md
  else
    echo "- reports/last-run.md missing"
  fi
  echo

  echo "## pipeline.last.log (tail, redacted)"
  echo '```'
  (tail -n 80 logs/pipeline.last.log 2>/dev/null || echo '(empty)') | redact
  echo '```'
  echo

  echo "## Container smoke"
  if command -v docker >/dev/null 2>&1; then
    echo '```'
    /usr/bin/docker compose run --rm --no-deps worker python -c \
      "import yt_dlp; print('yt_dlp', yt_dlp.version.__version__)" 2>&1 | redact | tail -n 20 \
      || echo 'docker compose run failed'
    echo '```'
    echo
    echo "### yt-dlp -F sample Shorts (timeout 45s)"
    echo '```'
    timeout 45 /usr/bin/docker compose run --rm --no-deps worker \
      yt-dlp -F "https://www.youtube.com/shorts/jNQXAC9IVRw" 2>&1 | redact | tail -n 40 \
      || echo 'yt-dlp -F failed or timed out'
    echo '```'
  else
    echo "- docker not available on host"
  fi
} > "$OUT"

echo "Wrote $OUT"

# Optional Telegram document
if [ -f .env ] && grep -Eq '^TELEGRAM_NOTIFY=(true|1|yes)' .env; then
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r')
  CHAT=$(grep -E '^TELEGRAM_OWNER_CHAT_ID=' .env | tail -1 | cut -d= -f2- | tr -d '\r')
  if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/sendDocument" \
      -F chat_id="$CHAT" \
      -F caption="🔎 diagnose.md $TS" \
      -F document=@"$OUT" >/dev/null || true
    echo "Sent diagnose.md to Telegram"
  fi
fi

# Optional publish to run-reports branch
if [ -x scripts/publish_run_report.sh ]; then
  # temporarily alias last-run for publisher reuse
  cp "$OUT" reports/last-run.md
  scripts/publish_run_report.sh || true
fi

echo "diagnose_exit=0"
