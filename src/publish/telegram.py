"""Send videos via Telegram bot."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


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
