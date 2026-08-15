"""Telegram Business Stories publisher adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.publish.base import PublishMeta, PublishResult
from src.publish.telegram_story import (
    TelegramStoryError,
    discover_business_connection_id,
    prepare_story_video,
    post_story_video,
)


class TelegramStoryPublisher:
    name = "telegram_story"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        flag = getattr(settings, "publish_telegram_story", False) or getattr(
            settings, "telegram_story_upload", False
        )
        if not flag:
            return False
        return bool(settings.telegram_bot_token)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not (
            getattr(settings, "publish_telegram_story", False)
            or getattr(settings, "telegram_story_upload", False)
        ):
            return PublishResult.skipped(self.name, "PUBLISH_TELEGRAM_STORY off")
        if not settings.telegram_bot_token:
            return PublishResult.skipped(self.name, "missing TELEGRAM_BOT_TOKEN")
        try:
            conn = (settings.telegram_business_connection_id or "").strip()
            if not conn:
                conn = discover_business_connection_id(settings.telegram_bot_token) or ""
            if not conn:
                cache = settings.data_dir / "business_connection.id"
                if cache.exists():
                    conn = cache.read_text(encoding="utf-8").strip()
            if not conn:
                return PublishResult.skipped(
                    self.name, "missing TELEGRAM_BUSINESS_CONNECTION_ID"
                )
            prepared = settings.data_dir / f"story_{video.stem}.mp4"
            prepare_story_video(video, prepared)
            story = post_story_video(
                settings.telegram_bot_token,
                conn,
                prepared,
                caption=(meta.caption or meta.title or "")[:500],
                active_period=settings.telegram_story_active_period,
            )
            return PublishResult.ok(
                self.name,
                detail={
                    "story_id": story.get("id"),
                    "chat": (story.get("chat") or {}).get("id"),
                },
            )
        except TelegramStoryError as exc:
            return PublishResult.failed(self.name, str(exc))
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))
