#!/bin/bash
set -eu
cd /opt/kontent-zavod

rm -f .github/workflows/deploy.yml
git fetch origin main
git reset --hard origin/main

add_env() {
  key="$1"
  val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

add_env TRANSCRIBE_BACKEND openai
add_env TARGET_DURATION_MIN 30
add_env TARGET_DURATION_MAX 40
add_env OPENAI_WHISPER_MODEL whisper-1

echo "=== env ==="
grep -E "^(TRANSCRIBE_BACKEND|TARGET_DURATION|OPENAI_WHISPER|OPENAI_API_KEY|YOUTUBE_API_KEY|IG_)" .env | sed 's/=.*/=***/' || true

docker compose build worker

docker compose run --rm worker python -c 'from src.config import load_settings; s=load_settings(); print("backend", s.transcribe_backend); print("duration", s.target_duration_min, s.target_duration_max); print("ig", len(s.instagram.hashtags))'

echo DEPLOY_OK
