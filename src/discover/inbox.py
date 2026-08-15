"""Manual URL inbox for discovery (YouTube Shorts + Instagram Reels)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from src.config import Settings
from src.db import Database
from src.models import SourceMeta

logger = logging.getLogger(__name__)

YT_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
IG_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)"
)

YOUTUBE_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


def extract_youtube_id(url: str) -> str | None:
    match = YT_PATTERN.search(url.strip())
    return match.group(1) if match else None


def extract_instagram_id(url: str) -> str | None:
    match = IG_PATTERN.search(url.strip())
    return match.group(1) if match else None


# Back-compat alias
extract_video_id = extract_youtube_id


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
        consumed: list[str] = []

        for line in lines:
            yt_id = extract_youtube_id(line)
            ig_id = extract_instagram_id(line)
            if yt_id:
                source_id = yt_id
                platform = "youtube"
            elif ig_id:
                source_id = f"ig_{ig_id}"
                platform = "instagram"
            else:
                logger.warning("Skipping invalid inbox URL: %s", line)
                remaining.append(line)
                continue

            if self.db.should_skip_discovery(source_id):
                consumed.append(line)
                continue

            if platform == "youtube":
                meta = self._fetch_youtube_meta(yt_id, line)
            else:
                meta = SourceMeta(
                    source_id=source_id,
                    url=line if line.startswith("http") else f"https://www.instagram.com/reel/{ig_id}/",
                    title=f"Inbox Instagram {ig_id}",
                    platform="instagram",
                    query="inbox",
                    score=1e9,  # prefer manual inbox over auto discovery
                )

            if meta:
                if platform == "youtube":
                    meta.score = max(meta.score, 1e9)
                    meta.query = meta.query or "inbox"
                results.append(meta)
                consumed.append(line)
            else:
                remaining.append(line)

        if consumed:
            self.processed_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive = self.processed_dir / f"urls_{stamp}.txt"
            archive.write_text("\n".join(consumed) + "\n", encoding="utf-8")
            self.urls_file.write_text(
                "\n".join(remaining) + ("\n" if remaining else ""),
                encoding="utf-8",
            )

        return results

    def _fetch_youtube_meta(self, video_id: str, original_url: str) -> SourceMeta | None:
        if not self.settings.youtube_api_key:
            return SourceMeta(
                source_id=video_id,
                url=original_url or f"https://www.youtube.com/shorts/{video_id}",
                title=f"Inbox video {video_id}",
                platform="youtube",
                query="inbox",
                score=1e9,
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
                    platform="youtube",
                    query="inbox",
                    score=1e9,
                )
        except Exception as exc:
            logger.error("Failed to fetch inbox video %s: %s", video_id, exc)
            return None
