"""Send videos and breakdown messages via Telegram bot."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from src.models import SourceMeta, TranscriptResult

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4096


def send_message(bot_token: str, chat_id: str, text: str) -> dict:
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        raise RuntimeError("TELEGRAM_OWNER_CHAT_ID not set")

    url = API.format(token=bot_token, method="sendMessage")
    resp = httpx.post(
        url,
        json={"chat_id": chat_id, "text": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def _split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = text
    while current:
        if len(current) <= limit:
            chunks.append(current)
            break
        split_at = current.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(current[:split_at].rstrip())
        current = current[split_at:].lstrip()
    return chunks


def send_messages(bot_token: str, chat_id: str, text: str) -> None:
    for chunk in _split_message(text):
        send_message(bot_token, chat_id, chunk)
        logger.info("Sent Telegram message chunk (%d chars)", len(chunk))


def _platform_label(meta: SourceMeta) -> str:
    return "Instagram" if meta.platform == "instagram" else "YouTube Shorts"


def format_source_breakdown(
    meta: SourceMeta,
    transcript: TranscriptResult,
    structure_analysis: str = "",
) -> str:
    duration = f"{meta.duration_sec:.0f} сек" if meta.duration_sec else "—"
    score = f"{meta.score:,.0f}" if meta.score else "—"
    views = f"{meta.views:,}".replace(",", " ")

    lines = [
        f"🔥 Залетевший Reels ({_platform_label(meta)})",
        "",
        meta.title,
        f"Автор: {meta.channel or '—'}",
        f"Просмотры: {views} · score: {score} · {duration}",
        f"Ссылка: {meta.url}",
    ]
    if meta.query:
        lines.append(f"Источник: {meta.query}")

    if structure_analysis:
        lines.extend(["", "📊 Разбор структуры:", structure_analysis])

    lines.extend(["", "📝 Транскрипт:", transcript.text or "(пусто)"])
    return "\n".join(lines)


def send_source_breakdown(
    bot_token: str,
    chat_id: str,
    meta: SourceMeta,
    transcript: TranscriptResult,
    structure_analysis: str = "",
) -> None:
    text = format_source_breakdown(meta, transcript, structure_analysis)
    send_messages(bot_token, chat_id, text)
    logger.info("Sent source breakdown for %s", meta.source_id)


def send_video(
    bot_token: str,
    chat_id: str,
    video_path: Path,
    caption: str,
) -> dict:
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        raise RuntimeError("TELEGRAM_OWNER_CHAT_ID not set")
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    url = API.format(token=bot_token, method="sendVideo")
    with video_path.open("rb") as video_file:
        resp = httpx.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
                "supports_streaming": "true",
            },
            files={"video": (video_path.name, video_file, "video/mp4")},
            timeout=300.0,
        )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    logger.info("Sent video to chat %s", chat_id)
    return data


def notify_owner(
    bot_token: str,
    owner_chat_id: str,
    video_path: Path,
    caption: str,
) -> dict:
    """Deliver rendered video to owner's private chat."""
    return send_video(bot_token, owner_chat_id, video_path, caption)


def send_document(
    bot_token: str,
    chat_id: str,
    file_path: Path,
    caption: str = "",
) -> dict:
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        raise RuntimeError("TELEGRAM_OWNER_CHAT_ID not set")
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    url = API.format(token=bot_token, method="sendDocument")
    with file_path.open("rb") as doc:
        resp = httpx.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
            },
            files={"document": (file_path.name, doc, "text/markdown")},
            timeout=120.0,
        )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    logger.info("Sent document %s to chat %s", file_path.name, chat_id)
    return data
