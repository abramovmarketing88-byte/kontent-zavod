"""Manual URL inbox for discovery."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from src.config import Settings
from src.db import Database
from src.models import SourceMeta

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)([A-Za-z0-9_-]{11})"
)

YOUTUBE_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


def extract_video_id(url: str) -> str | None:
    match = URL_PATTERN.search(url.strip())
    return match.group(1) if match else None


class InboxDiscoverer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.urls_file = settings.inbox_dir / "urls.txt"
        self.processed_dir = settings.inbox_dir / "processed"

    def discover(self) -> list[SourceMeta]:
        if not self.urls_file.exists():
            return []

        lines = [
            line.strip()
            for line in self.urls_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            return []

        results: list[SourceMeta] = []
        remaining: list[str] = []

        for line in lines:
            video_id = extract_video_id(line)
            if not video_id:
                logger.warning("Skipping invalid inbox URL: %s", line)
                continue
            if self.db.should_skip_discovery(video_id):
                continue

            meta = self._fetch_meta(video_id, line)
            if meta:
                results.append(meta)
            else:
                remaining.append(line)

        # Move processed URLs out of inbox
        if results:
            stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            archive = self.processed_dir / f"urls_{stamp}.txt"
            archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.urls_file.write_text(
                "\n".join(remaining) + ("\n" if remaining else ""),
                encoding="utf-8",
            )

        return results

    def _fetch_meta(self, video_id: str, original_url: str) -> SourceMeta | None:
        if not self.settings.youtube_api_key:
            return SourceMeta(
                source_id=video_id,
                url=original_url or f"https://www.youtube.com/shorts/{video_id}",
                title=f"Inbox video {video_id}",
            )

        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": self.settings.youtube_api_key,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(YOUTUBE_VIDEOS, params=params)
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    return None
                item = items[0]
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                return SourceMeta(
                    source_id=video_id,
                    url=original_url or f"https://www.youtube.com/shorts/{video_id}",
                    title=snippet.get("title", ""),
                    views=int(stats.get("viewCount", 0)),
                    published_at=snippet.get("publishedAt", ""),
                    channel=snippet.get("channelTitle", ""),
                )
        except Exception as exc:
            logger.error("Failed to fetch inbox video %s: %s", video_id, exc)
            return None
