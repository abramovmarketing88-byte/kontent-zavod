# Kontent Zavod

Автоматический контент-завод для faceless Reels (Instagram).

## Разовый заказ (не ждать 09:00)

Сервер сам **не** смотрит лейблы GitHub напрямую. Каждые 15 минут он делает `git pull` `main`. Если в `triggers/run-once.id` новый id — сразу собирает один ролик и шлёт его в Telegram (тот же бот, что в `mcp.json`).

Триггер **сразу помечается выполненным** (чтобы cron не слал «⏳» каждые 15 минут). Если сборка упала — в личку придёт ❌/💥 с текстом ошибки; повтор только новым заказом.

1. **GitHub → Actions → "Run once now" → Run workflow**
2. Или лейбл **`run-now`** на Issue
3. Или комментарий **`/run-now`** в Issue
4. Или по SSH, сразу, без ожидания pull:

```bash
bash /opt/kontent-zavod/scripts/run_once.sh
# диагностика:
tail -n 80 /opt/kontent-zavod/logs/pipeline.last.log
tail -n 40 /opt/kontent-zavod/logs/run-once.log
```

В личку: «⏳…» → разбор Reels → готовый mp4 (или ❌ с причиной + файл `last-run.md`).

### Логи для отладки (чтобы агент видел проблему)

На сервере после прогона:

```bash
# Полная диагностика (прокси, cron, DB, last-run) → reports/diagnose.md + Telegram
bash /opt/kontent-zavod/scripts/diagnose.sh

cat /opt/kontent-zavod/reports/last-run.md
tail -n 100 /opt/kontent-zavod/logs/pipeline.last.log
```

Предсказуемый smoke (одна ссылка из inbox):

```bash
bash /opt/kontent-zavod/scripts/smoke_e2e.sh 'https://www.youtube.com/shorts/XXXX'
```

Тема наугад без исходного ролика — положи текст в `inbox/topic.txt` и закажи run-once:

```bash
echo 'Нейросети: раньше день работы, сейчас 5 минут' > /opt/kontent-zavod/inbox/topic.txt
# или через git: файл inbox/topic.txt + новый triggers/run-once.id
```

При падении бот присылает **`last-run.md`** в Telegram.  
Опционально сервер пушит тот же отчёт в ветку **`run-reports`** (нужен `GITHUB_TOKEN` или write deploy key) — тогда агент читает его прямо с GitHub.

**Прокси:** compose передаёт `HTTP_PROXY=http://127.0.0.1:7890`, но entrypoint **сбрасывает** его, если mihomo мёртв (`PROXY_REQUIRED=false` по умолчанию).

## Локальный прогон (без VPS)

Если сервера нет под рукой — гоняй прямо в Cloud Agent / на ноуте:

```bash
# минимальные секреты в .env или Cursor Secrets:
# OPENROUTER_API_KEY, YOUTUBE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID
# (ElevenLabs / Pexels / HeyGen опциональны: Edge TTS + placeholder B-roll + faceless)

bash scripts/run_local.sh 'https://www.youtube.com/shorts/XXXX'
# или автопоиск ниши:
bash scripts/run_local.sh
```

Скрипт сам сбрасывает `HTTP_PROXY` (чтобы не ходить в мёртвый mihomo с VPS), ставит `RENDERER=faceless` и пишет `reports/last-run.md`.

Docker без прокси: `docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm worker python -m src.pipeline --once`

## Быстрый старт

1. Скопируй `.env.example` → `.env` и заполни ключи API
2. Отредактируй `brand/prompt.md` под свой голос и нишу
3. Запуск:

```bash
# Локально
pip install .
python -m src.pipeline --once

# Docker
docker compose up --build
```

## Что делает

1. Ищет залетевшие YouTube Shorts по нише (русский бизнес/маркетинг)
2. Читает inbox (`inbox/urls.txt`) — ручные ссылки
3. Транскрибирует через Whisper
4. Переписывает сценарий через Cursor SDK (fallback: OpenRouter / OpenAI)
5. Озвучивает ElevenLabs + субтитры karaoke
6. Собирает 9:16 видео из Pexels B-roll
7. Кладёт mp4 + caption.txt в `output/YYYY-MM-DD/`

## Структура

- `brand/prompt.md` — бренд-голос
- `brand/voice.json` — настройки ElevenLabs
- `config/niche.yaml` — поисковые запросы и пороги
- `jobs/{video_id}/` — артефакты каждого ролика
- `output/` — готовые mp4

## API ключи

| Сервис | Где взять |
|--------|-----------|
| Cursor | cursor.com/dashboard/integrations |
| ElevenLabs | elevenlabs.io/app/settings/api-keys |
| YouTube | console.cloud.google.com |
| Pexels | pexels.com/api |
| OpenRouter (fallback) | openrouter.ai/keys |
| OpenAI (fallback, alt.) | platform.openai.com |

## Деплой на сервер (24/7 + Telegram утром)

### Что нужно на VPS

| Параметр | Рекомендация |
|----------|--------------|
| ОС | Ubuntu 22.04+ |
| RAM | 4 GB (Whisper + ffmpeg) |
| Диск | 20 GB+ |
| Регион | EU/US (YouTube + Telegram без VPN) |

### 1. Перенос проекта

```bash
# на сервере
git clone <your-repo> kontent-zavod
cd kontent-zavod
cp .env.example .env
nano .env   # все ключи + Telegram + HeyGen
```

Или с локальной машины:
```bash
rsync -avz --exclude output --exclude jobs --exclude .env \
  ./ user@your-server:/opt/kontent-zavod/
scp .env user@your-server:/opt/kontent-zavod/.env
```

### 2. Настрой `.env` для ежедневного поста

```env
RENDERER=hybrid
HEYGEN_AVATAR_ID=0fc4e7ac2247411782d19b7d2d29892c

TELEGRAM_BOT_TOKEN=...          # тот же, что в mcp.json
TELEGRAM_OWNER_CHAT_ID=...      # python scripts/telegram_chat_id.py
TELEGRAM_NOTIFY=true            # слать ролик тебе в личку утром

MAX_VIDEOS_PER_RUN=1
DAILY_AT=09:00
SCHEDULE_TZ=Europe/Moscow
```

Бот **не** постит в канал — только шлёт готовый mp4 тебе в DM для проверки.
Перед первым запуском: напиши боту `/start`, затем `python scripts/telegram_chat_id.py`.

### 3. Запуск через Docker

```bash
docker compose up -d --build
docker compose logs -f worker
```

Контейнер `restart: unless-stopped` — перезапускается после ребута сервера.

### 4. Без Docker (systemd)

```bash
pip install .
sudo cp scripts/kontent-zavod.service /etc/systemd/system/
sudo systemctl enable --now kontent-zavod
journalctl -u kontent-zavod -f
```

## Telegram Business Stories

Бот-ассистент на Business может постить сторис через `postStory` (нужно право `can_manage_stories`).

```env
TELEGRAM_STORY_UPLOAD=true
# optional if auto-discover from getUpdates fails:
# TELEGRAM_BUSINESS_CONNECTION_ID=...
TELEGRAM_STORY_ACTIVE_PERIOD=86400
```

Видео перекодируется в **720×1280 H.265** (требование TG).  
Разовая выгрузка последнего ролика:

```bash
printf '%s\n' "story-$(date -u +%Y%m%dT%H%M%SZ)" > triggers/telegram-story-once.id
bash scripts/auto_update.sh
# или
docker compose run --rm --no-deps worker python -m src.publish.telegram_story
```

## YouTube Shorts (выгрузка)

`YOUTUBE_API_KEY` — только **поиск**. Чтобы **залить** Short, нужен OAuth:

```env
YOUTUBE_CLIENT_ID=....apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...
YOUTUBE_UPLOAD=true
YOUTUBE_PRIVACY=public
```

Scope: `https://www.googleapis.com/auth/youtube.upload`  
(Google Cloud → OAuth Desktop client → [OAuth Playground](https://developers.google.com/oauthplayground/) → получить refresh_token).

Разовый апдейт последнего ролика из `output/`:

```bash
# на VPS после git pull
printf '%s\n' "manual-$(date -u +%Y%m%dT%H%M%SZ)" > triggers/youtube-upload-once.id
bash scripts/auto_update.sh
# или сразу:
docker compose run --rm --no-deps worker python -m src.publish.youtube
```

Если `YOUTUBE_UPLOAD=true`, каждый успешный прогон сам льёт Short после Telegram.

### 5. Откуда берутся ролики

1. **Автопоиск** — `config/niche.yaml` (YouTube Shorts по запросам)
2. **Inbox** — кидай ссылки в `inbox/urls.txt` на сервере

Дедупликация в SQLite (`data/factory.db`) — один source_id не обработается дважды.

### 6. Проверка перед продом

```bash
python -m src.pipeline --once   # один прогон без ожидания утра
```

### Стоимость API (ориентир)

~$1/день: HeyGen intro (~10 сек) + ElevenLabs + OpenRouter fallback.
