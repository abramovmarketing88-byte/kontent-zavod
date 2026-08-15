"""Run all enabled publishers after a render."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.publish.adapters_telegram_dm import TelegramDmPublisher
from src.publish.adapters_telegram_story import TelegramStoryPublisher
from src.publish.adapters_youtube import YouTubeShortsPublisher
from src.publish.base import PublishMeta, PublishResult
from src.publish.instagram import InstagramReelsPublisher
from src.publish.max_messenger import MaxChannelPublisher, MaxStoriesPublisher
from src.publish.tiktok import TikTokPublisher
from src.publish.vk import VkPublisher
from src.publish.youtube import find_latest_output_video

logger = logging.getLogger(__name__)


def default_publishers() -> list[Any]:
    """Order: DM → YT → TG story → VK → IG → MAX → TikTok (+ MAX stories stub)."""
    return [
        TelegramDmPublisher(),
        YouTubeShortsPublisher(),
        TelegramStoryPublisher(),
        VkPublisher(),
        InstagramReelsPublisher(),
        MaxChannelPublisher(),
        MaxStoriesPublisher(),
        TikTokPublisher(),
    ]


class PublishOrchestrator:
    def __init__(
        self,
        settings: Any,
        *,
        publishers: list[Any] | None = None,
        notify: Callable[[str], None] | None = None,
        report: Any | None = None,
    ) -> None:
        self.settings = settings
        self.publishers = publishers or default_publishers()
        self.notify = notify
        self.report = report

    def publish_all(self, video: Path, meta: PublishMeta) -> list[PublishResult]:
        if not getattr(self.settings, "publish_enabled", True):
            result = PublishResult.skipped("all", "PUBLISH_ENABLED=false")
            self._record([result])
            return [result]

        results: list[PublishResult] = []
        for pub in self.publishers:
            name = getattr(pub, "name", pub.__class__.__name__)
            try:
                if self.report is not None:
                    self.report.stage("publish", name)
                if not pub.enabled(self.settings):
                    # Still call publish for a clear skipped reason when flag off
                    res = pub.publish(video, meta, self.settings)
                else:
                    res = pub.publish(video, meta, self.settings)
            except Exception as exc:
                logger.exception("Publisher %s crashed: %s", name, exc)
                res = PublishResult.failed(name, str(exc))
            results.append(res)
            logger.info("publish %s", res.line())
            if self.report is not None and res.status == "failed":
                self.report.errors.append(f"{res.platform}: {res.error}")

        self._record(results)
        summary = self.summary_text(results)
        if self.notify is not None and summary:
            try:
                self.notify(summary)
            except Exception as exc:
                logger.warning("Publish summary notify failed: %s", exc)
        return results

    def summary_text(self, results: list[PublishResult]) -> str:
        if not results:
            return ""
        lines = ["📣 Публикация:", *[r.line() for r in results]]
        return "\n".join(lines)

    def _record(self, results: list[PublishResult]) -> None:
        data_dir = Path(self.settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "publish_state.json"
        payload = {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "results": [
                {
                    "platform": r.platform,
                    "status": r.status,
                    "url": r.url,
                    "error": r.error,
                    "detail": r.detail,
                }
                for r in results
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if self.report is not None and hasattr(self.report, "publish_results"):
            self.report.publish_results = payload["results"]


def publish_latest(settings: Any, *, notify: Callable[[str], None] | None = None) -> list[PublishResult]:
    video = find_latest_output_video(settings.output_dir)
    if video is None:
        return [PublishResult.failed("all", "No video in output/")]
    caption_file = video.with_name(video.stem + ".txt")
    caption = ""
    if caption_file.exists():
        caption = caption_file.read_text(encoding="utf-8").strip()
    meta = PublishMeta(
        title=video.stem.replace("-", " "),
        caption=caption or video.stem.replace("-", " "),
        hashtags=[],
        video_path=video,
    )
    return PublishOrchestrator(settings, notify=notify).publish_all(video, meta)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.telegram import send_message

    load_dotenv()
    parser = argparse.ArgumentParser(description="Publish latest output video to all enabled platforms")
    parser.add_argument("video", nargs="?", help="Optional path to mp4")
    args = parser.parse_args(argv)
    settings = load_settings()

    def _tg(text: str) -> None:
        if settings.telegram_notify and settings.telegram_bot_token and settings.telegram_owner_chat_id:
            send_message(settings.telegram_bot_token, settings.telegram_owner_chat_id, text)

    if args.video:
        video = Path(args.video)
        meta = PublishMeta(title=video.stem.replace("-", " "), caption=video.stem)
        results = PublishOrchestrator(settings, notify=_tg).publish_all(video, meta)
    else:
        results = publish_latest(settings, notify=_tg)

    for r in results:
        print(r.line())
    if any(r.status == "failed" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
