"""MAX messenger: post video to channel/chat; stories stub until Bot API supports it."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from src.publish.base import PublishMeta, PublishResult
from src.publish.media_prep import join_caption

logger = logging.getLogger(__name__)

MAX_API = "https://platform-api2.max.ru"


class MaxChannelPublisher:
    name = "max_channel"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        if not getattr(settings, "publish_max", False):
            return False
        return bool(settings.max_bot_token and settings.max_chat_id)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not getattr(settings, "publish_max", False):
            return PublishResult.skipped(self.name, "PUBLISH_MAX off")
        if not settings.max_bot_token or not settings.max_chat_id:
            return PublishResult.skipped(self.name, "missing MAX_BOT_TOKEN / MAX_CHAT_ID")
        if not video.exists():
            return PublishResult.failed(self.name, f"video not found: {video}")

        text = join_caption(meta.caption or meta.title, meta.hashtags, max_len=4000)
        headers = {"Authorization": settings.max_bot_token}

        try:
            with httpx.Client(timeout=120.0, headers=headers) as client:
                # 1) get upload URL
                up_init = client.post(f"{MAX_API}/uploads", params={"type": "video"})
                if up_init.status_code >= 400:
                    raise RuntimeError(
                        f"MAX uploads init failed ({up_init.status_code}): {up_init.text[:300]}"
                    )
                init_data = up_init.json()
                upload_url = init_data.get("url")
                token = init_data.get("token")
                if not upload_url or not token:
                    raise RuntimeError(f"MAX uploads missing url/token: {init_data}")

                # 2) upload bytes
                with video.open("rb") as handle:
                    put = client.post(
                        upload_url,
                        content=handle.read(),
                        headers={"Content-Type": "video/mp4"},
                        timeout=600.0,
                    )
                if put.status_code >= 400:
                    raise RuntimeError(
                        f"MAX upload PUT failed ({put.status_code}): {put.text[:300]}"
                    )

                # 3) send message with video attachment
                chat_id = settings.max_chat_id
                # chat_id may be int-like
                try:
                    chat_param: int | str = int(chat_id)
                except ValueError:
                    chat_param = chat_id
                msg = client.post(
                    f"{MAX_API}/messages",
                    params={"chat_id": chat_param},
                    json={
                        "text": text,
                        "attachments": [
                            {"type": "video", "payload": {"token": token}},
                        ],
                    },
                )
                body = msg.json() if msg.content else {}
                if msg.status_code >= 400:
                    raise RuntimeError(
                        f"MAX messages failed ({msg.status_code}): {msg.text[:300]}"
                    )
                logger.info("MAX channel video posted chat=%s", chat_param)
                return PublishResult.ok(
                    self.name,
                    detail={"chat_id": chat_param, "message": body},
                )
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))


class MaxStoriesPublisher:
    """Placeholder: MAX user stories exist in-app; Bot API stories not public yet."""

    name = "max_stories"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        return bool(getattr(settings, "publish_max_stories", False))

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not getattr(settings, "publish_max_stories", False):
            return PublishResult.skipped(self.name, "PUBLISH_MAX_STORIES off")
        return PublishResult.skipped(
            self.name,
            "stories_api_unavailable — MAX Bot API has no postStory yet; "
            "use max_channel for video posts",
        )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.youtube import find_latest_output_video

    load_dotenv()
    parser = argparse.ArgumentParser(description="Post latest Reel to MAX channel")
    parser.add_argument("video", nargs="?")
    args = parser.parse_args(argv)
    settings = load_settings()
    settings.publish_max = True  # type: ignore[attr-defined]
    settings.publish_enabled = True  # type: ignore[attr-defined]
    video = Path(args.video) if args.video else find_latest_output_video(settings.output_dir)
    if video is None:
        print("No video in output/", file=sys.stderr)
        return 2
    result = MaxChannelPublisher().publish(
        video, PublishMeta(title=video.stem, caption=video.stem), settings
    )
    print(result.line())
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
