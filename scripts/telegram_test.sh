#!/bin/bash
set -eu
cd /opt/kontent-zavod
/usr/bin/docker compose run --rm worker python -c "
import httpx
from src.config import load_settings
s = load_settings()
text = '✅ Kontent Zavod задеплоен на debian-home.\n\nКаждый день в 09:00 МСК — новый Reels в эту личку.'
r = httpx.post(
    f'https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage',
    json={'chat_id': s.telegram_owner_chat_id, 'text': text},
    timeout=60,
)
print(r.status_code, r.text[:200])
"
