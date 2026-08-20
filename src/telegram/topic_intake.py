"""Poll Telegram for topic orders — text or voice → inbox/topic.txt + run-once."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import httpx

from src.analyze.transcriber import transcribe_audio
from src.config import Settings, load_settings
from src.publish.telegram import send_message

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
HELP_TEXT = (
    "🎬 Тема → Reels\n\n"
    "Напиши тему текстом или голосовым — проанализирую интернет, "
    "соберу вирусный сценарий под тебя, озвучу и пришлю ролик.\n\n"
    "Примеры:\n"
    "• у жизни нет черновика\n"
    "• /topic 5 способов экономить время с ИИ\n\n"
    "Голосовое тоже ок — распознаю и возьму как тему."
)


def format_topic_brief(topic: str) -> str:
    """Turn a short phrase into a pipeline-ready brief."""
    raw = " ".join(topic.split()).strip()
    if not raw:
        return ""
    title = raw[0].upper() + raw[1:] if raw else raw
    body = (
        f"Сделай Reels на тему: {raw}.\n"
        "Перед сценарием — проанализируй интернет: факты, тренды, вирусные углы.\n"
        "Тон мотивирующий и живой. Структура: хук → мысль → 2 примера → CTA.\n"
        "30–40 секунд, русский."
    )
    return f"{title}\n\n{body}"


def build_topic_file(topic: str, *, run_id: str | None = None) -> str:
    rid = (run_id or uuid.uuid4().hex)[:12]
    brief = format_topic_brief(topic)
    return f"#run:{rid}\n#telegram\n{brief}\n"


def parse_topic_text(text: str) -> str | None:
    """Extract topic from a plain message or /topic command."""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("/topic"):
        rest = text[6:].strip()
        if rest.startswith("@"):
            parts = rest.split(None, 1)
            rest = parts[1] if len(parts) > 1 else ""
        return rest.strip() or None
    if text.startswith("/"):
        return None
    return text


def bump_run_once_trigger(root: Path) -> str:
    trigger = root / "triggers" / "run-once.id"
    trigger.parent.mkdir(parents=True, exist_ok=True)
    new_id = uuid.uuid4().hex
    trigger.write_text(new_id + "\n", encoding="utf-8")
    return new_id


def queue_topic(settings: Settings, topic: str) -> tuple[str, str]:
    """Write inbox/topic.txt and bump run-once trigger. Returns (run_id, trigger_id)."""
    run_id = uuid.uuid4().hex[:12]
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    topic_path = settings.inbox_dir / "topic.txt"
    topic_path.write_text(build_topic_file(topic, run_id=run_id), encoding="utf-8")
    trigger_id = bump_run_once_trigger(settings.root)
    logger.info("Queued topic run_id=%s trigger=%s title=%r", run_id, trigger_id, topic[:80])
    return run_id, trigger_id


def _api(token: str, method: str) -> str:
    return API.format(token=token, method=method)


def _offset_path(settings: Settings) -> Path:
    return settings.data_dir / "telegram_topic.offset"


def _load_offset(settings: Settings) -> int:
    path = _offset_path(settings)
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return 0


def _save_offset(settings: Settings, offset: int) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _offset_path(settings).write_text(str(offset) + "\n", encoding="utf-8")


def _download_telegram_file(token: str, file_id: str, dest: Path) -> Path:
    with httpx.Client(timeout=120.0) as client:
        meta = client.get(_api(token, "getFile"), params={"file_id": file_id})
        meta.raise_for_status()
        data = meta.json()
        if not data.get("ok"):
            raise RuntimeError(f"getFile failed: {data}")
        file_path = data["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        resp = client.get(url)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
    return dest


def _transcribe_voice(settings: Settings, token: str, file_id: str) -> str:
    tmp = settings.data_dir / "telegram_voice"
    tmp.mkdir(parents=True, exist_ok=True)
    audio_path = tmp / f"{uuid.uuid4().hex}.ogg"
    try:
        _download_telegram_file(token, file_id, audio_path)
        result = transcribe_audio(settings, audio_path)
        text = (result.text or "").strip()
        if not text:
            raise RuntimeError("empty transcription")
        return text
    finally:
        audio_path.unlink(missing_ok=True)


def _owner_chat_id(settings: Settings) -> str:
    return str(settings.telegram_owner_chat_id or "").strip()


def _is_owner_message(settings: Settings, chat: dict) -> bool:
    owner = _owner_chat_id(settings)
    if not owner:
        return False
    return str(chat.get("id", "")) == owner


def _reply(settings: Settings, chat_id: str | int, text: str) -> None:
    send_message(settings.telegram_bot_token, str(chat_id), text)


def _handle_help(settings: Settings, chat_id: str | int) -> None:
    _reply(settings, chat_id, HELP_TEXT)


def _handle_topic(settings: Settings, chat_id: str | int, topic: str) -> bool:
    topic = " ".join(topic.split()).strip()
    if len(topic) < 3:
        _reply(
            settings,
            chat_id,
            "Слишком коротко. Напиши тему подробнее, например: у жизни нет черновика",
        )
        return False
    if len(topic) > 500:
        _reply(settings, chat_id, "Слишком длинно — уложись в ~500 символов или сожми мысль.")
        return False
    _, trigger_id = queue_topic(settings, topic)
    title = topic[0].upper() + topic[1:] if topic else topic
    _reply(
        settings,
        chat_id,
        f"⏳ Анализирую интернет и делаю Reels на тему:\n«{title}»\n\n"
        f"Заказ #{trigger_id[:8]} — пришлю ролик в личку.",
    )
    return True


def _extract_message(update: dict) -> dict | None:
    for key in ("message", "edited_message", "business_message"):
        msg = update.get(key)
        if msg:
            return msg
    return None


def process_updates(settings: Settings) -> int:
    """Poll Telegram once and queue topics from the owner. Returns topics queued."""
    token = (settings.telegram_bot_token or "").strip()
    owner = _owner_chat_id(settings)
    if not token or not owner:
        logger.debug("Telegram topic intake skipped: token or owner chat missing")
        return 0
    if not settings.telegram_topic_intake:
        return 0

    offset = _load_offset(settings)
    params = {
        "offset": offset,
        "timeout": 0,
        "allowed_updates": json.dumps(["message", "edited_message", "business_message"]),
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(_api(token, "getUpdates"), params=params)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        logger.warning("getUpdates failed: %s", data)
        return 0

    queued = 0
    max_update_id = offset
    for update in data.get("result") or []:
        update_id = int(update.get("update_id", 0))
        max_update_id = max(max_update_id, update_id + 1)
        msg = _extract_message(update)
        if not msg:
            continue
        chat = msg.get("chat") or {}
        if not _is_owner_message(settings, chat):
            continue

        chat_id = chat.get("id")
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if text.startswith("/start") or text.startswith("/help"):
            _handle_help(settings, chat_id)
            continue
        if text.startswith("/"):
            topic = parse_topic_text(text)
            if topic is None:
                if text.split()[0].lower() not in ("/topic",):
                    _reply(settings, chat_id, "Не понял команду. Просто напиши тему или /help")
                continue
        else:
            topic = parse_topic_text(text)

        if topic:
            if _handle_topic(settings, chat_id, topic):
                queued += 1
            continue

        voice = msg.get("voice") or msg.get("video_note")
        if voice:
            try:
                spoken = _transcribe_voice(settings, token, voice["file_id"])
                _reply(settings, chat_id, f"🎤 Услышал: «{spoken}»")
                if _handle_topic(settings, chat_id, spoken):
                    queued += 1
            except Exception as exc:
                logger.exception("Voice topic failed: %s", exc)
                _reply(
                    settings,
                    chat_id,
                    f"Не смог распознать голосовое: {exc}\nНапиши тему текстом.",
                )
            continue

    if max_update_id > offset:
        _save_offset(settings, max_update_id)
    return queued


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = load_settings()
    n = process_updates(settings)
    if n:
        logger.info("Queued %d topic(s) from Telegram", n)


if __name__ == "__main__":
    main()
