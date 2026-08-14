"""Send latest rendered video to owner's Telegram DM."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_settings
from src.publish.telegram import notify_owner


def main() -> None:
    load_dotenv()
    settings = load_settings()

    root = Path(__file__).resolve().parents[1]
    video = root / "jobs" / "content-factory-launch" / "final.mp4"
    if not video.exists():
        print(f"Video not found: {video}", file=sys.stderr)
        sys.exit(1)

    caption_path = root / "output" / "2026-08-14" / "telegram_post.txt"
    caption = (
        caption_path.read_text(encoding="utf-8").strip()
        if caption_path.exists()
        else "Test video from Kontent Zavod"
    )

    notify_owner(
        settings.telegram_bot_token,
        settings.telegram_owner_chat_id,
        video,
        caption,
    )
    print("Sent to your Telegram DM")


if __name__ == "__main__":
    main()
