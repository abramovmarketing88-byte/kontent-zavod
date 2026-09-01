"""Telegram DM publisher adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.publish.base import PublishMeta, PublishResult
from src.publish.telegram import notify_owner


class TelegramDmPublisher:
    name = "telegram_dm"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        if not getattr(settings, "publish_telegram_dm", True):
            return False
        return bool(settings.telegram_bot_token and settings.telegram_owner_chat_id)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not self.enabled(settings):
            return PublishResult.skipped(self.name, "disabled or missing TELEGRAM_*")
        order_label = f" · заказ #{meta.order_id}" if meta.order_id else ""
        caption = (
            f"🎬 Готово вертикальное видео{order_label}\n\n{meta.caption}\n\n"
            f"{' '.join(meta.hashtags)}"
        ).strip()
        buttons = None
        if meta.order_id:
            buttons = {
                "inline_keyboard": [
                    [{"text": "📣 Опубликовать", "callback_data": f"order:publish:{meta.order_id}"}],
                    [
                        {"text": "✏️ Изменить", "callback_data": f"order:edit:{meta.order_id}"},
                        {"text": "🎬 Новый Reels", "callback_data": "menu:new"},
                    ]
                ]
            }
        try:
            notify_owner(
                settings.telegram_bot_token,
                settings.telegram_owner_chat_id,
                video,
                caption[:1024],
                reply_markup=buttons,
            )
            return PublishResult.ok(self.name, detail={"chat_id": settings.telegram_owner_chat_id})
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))
