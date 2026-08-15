"""YouTube Shorts publisher adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.publish.base import PublishMeta, PublishResult
from src.publish.youtube import YouTubeUploadError, YouTubeUploader


class YouTubeShortsPublisher:
    name = "youtube_shorts"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        flag = getattr(settings, "publish_youtube", False) or getattr(
            settings, "youtube_upload", False
        )
        if not flag:
            return False
        return bool(
            settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        )

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not (
            getattr(settings, "publish_youtube", False)
            or getattr(settings, "youtube_upload", False)
        ):
            return PublishResult.skipped(self.name, "PUBLISH_YOUTUBE/YOUTUBE_UPLOAD off")
        if not (
            settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        ):
            return PublishResult.skipped(self.name, "missing YouTube OAuth credentials")
        try:
            uploader = YouTubeUploader(
                client_id=settings.youtube_client_id,
                client_secret=settings.youtube_client_secret,
                refresh_token=settings.youtube_refresh_token,
                privacy=settings.youtube_privacy,
                category_id=settings.youtube_category_id,
            )
            tags = [h.lstrip("#") for h in (meta.hashtags or []) if h]
            result = uploader.upload_short(
                video,
                title=meta.title_or_stem(video.stem),
                description=meta.description(),
                tags=tags,
            )
            return PublishResult.ok(
                self.name,
                url=result.get("url", ""),
                detail={"id": result.get("id"), "privacy": result.get("privacy")},
            )
        except YouTubeUploadError as exc:
            return PublishResult.failed(self.name, str(exc))
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))
