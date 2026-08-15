#!/usr/bin/env bash
# Run Kontent Zavod locally (Cloud Agent / laptop) — no VPS, no forced proxy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PROJECT_ROOT="$ROOT"
# Never inherit a dead VPS mihomo proxy in this environment
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy || true
export HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

# Local defaults: faceless (no HeyGen), notify on
export RENDERER="${RENDERER:-faceless}"
export TELEGRAM_NOTIFY="${TELEGRAM_NOTIFY:-true}"
export TRANSCRIBE_BACKEND="${TRANSCRIBE_BACKEND:-faster_whisper}"
export WHISPER_MODEL="${WHISPER_MODEL:-base}"
export MAX_VIDEOS_PER_RUN="${MAX_VIDEOS_PER_RUN:-1}"
export PROXY_REQUIRED=false

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  # Re-clear proxy after sourcing .env (VPS values would break local)
  unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy || true
  export HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""
  export RENDERER="${RENDERER:-faceless}"
fi

mkdir -p output jobs data logs reports inbox/processed

missing=0
require() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "MISSING: $name"
    missing=1
  else
    echo "OK: $name"
  fi
}

echo "=== Local run preflight ==="
if [ -n "${OPENROUTER_API_KEY:-}${OPENAI_API_KEY:-}${CURSOR_API_KEY:-}" ]; then
  echo "OK: LLM key (OpenRouter/OpenAI/Cursor)"
else
  echo "MISSING: OPENROUTER_API_KEY or OPENAI_API_KEY or CURSOR_API_KEY"
  missing=1
fi
require YOUTUBE_API_KEY
require TELEGRAM_BOT_TOKEN
require TELEGRAM_OWNER_CHAT_ID
echo "optional ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY:+set}"
echo "optional PEXELS_API_KEY=${PEXELS_API_KEY:+set}"
echo "RENDERER=$RENDERER"

if [ "$missing" -ne 0 ]; then
  echo
  echo "Add secrets in Cursor (or write .env), then re-run:"
  echo "  bash scripts/run_local.sh 'https://www.youtube.com/shorts/XXXX'"
  exit 2
fi

URL="${1:-}"
if [ -n "$URL" ]; then
  printf '%s\n' "$URL" > inbox/urls.txt
  echo "Inbox URL: $URL"
fi

python3 -m pip install -e . -q
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

python3 -m src.pipeline --once --notify-start
echo "Done. See reports/last-run.md and output/"
