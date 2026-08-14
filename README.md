# Kontent Zavod

Автоматический контент-завод для faceless Reels (Instagram).

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
