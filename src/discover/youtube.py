"""YouTube Shorts discovery via Data API v3."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from src.config import Settings
from src.db import Database
from src.models import SourceMeta

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


def _parse_duration(iso: str) -> float:
    """Parse ISO 8601 duration PT1M30S -> seconds."""
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        iso or "PT0S",
    )
    if not match:
        return 0.0
    hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _hours_since(published_at: str) -> float:
    if not published_at:
        return 1.0
    dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    return max(delta.total_seconds() / 3600, 1.0)


def _score(views: int, published_at: str) -> float:
    return views / _hours_since(published_at)


class YouTubeDiscoverer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.niche = settings.niche

    def discover(self, limit: int | None = None) -> list[SourceMeta]:
        if not self.settings.youtube_api_key:
            logger.warning("YOUTUBE_API_KEY not set — skipping YouTube discovery")
            return []

        candidates: dict[str, SourceMeta] = {}
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=self.niche.max_age_days)
        ).isoformat()

        with httpx.Client(timeout=30.0) as client:
            for query in self.niche.search_queries:
                search_items = self._search(client, query, published_after)
                if not search_items:
                    continue

                video_ids = [
                    item["id"]["videoId"]
                    for item in search_items
                    if item.get("id", {}).get("videoId")
                ]
                details = self._video_details(client, video_ids)

                for item in search_items:
                    vid = item.get("id", {}).get("videoId")
                    if not vid or vid not in details:
                        continue
                    if self.db.should_skip_discovery(vid):
                        continue

                    detail = details[vid]
                    stats = detail.get("statistics", {})
                    content = detail.get("contentDetails", {})
                    snippet = detail.get("snippet", item.get("snippet", {}))

                    views = int(stats.get("viewCount", 0))
                    duration = _parse_duration(content.get("duration", ""))

                    if views < self.niche.min_views:
                        continue
                    if duration <= 0 or duration > self.niche.max_duration_sec:
                        continue

                    published = snippet.get("publishedAt", "")
                    meta = SourceMeta(
                        source_id=vid,
                        url=f"https://www.youtube.com/shorts/{vid}",
                        title=snippet.get("title", ""),
                        views=views,
                        published_at=published,
                        channel=snippet.get("channelTitle", ""),
                        duration_sec=duration,
                        score=_score(views, published),
                        query=query,
                    )
                    candidates[vid] = meta

        ranked = sorted(candidates.values(), key=lambda m: m.score, reverse=True)
        cap = limit or self.settings.max_videos_per_run
        return ranked[:cap]

    def _search(
        self,
        client: httpx.Client,
        query: str,
        published_after: str,
    ) -> list[dict]:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoDuration": "short",
            "order": "viewCount",
            "publishedAfter": published_after,
            "maxResults": self.niche.top_n_per_query,
            "relevanceLanguage": "ru",
            "key": self.settings.youtube_api_key,
        }
        resp = client.get(YOUTUBE_SEARCH, params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    def _video_details(
        self,
        client: httpx.Client,
        video_ids: list[str],
    ) -> dict[str, dict]:
        if not video_ids:
            return {}
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": self.settings.youtube_api_key,
        }
        resp = client.get(YOUTUBE_VIDEOS, params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return {item["id"]: item for item in items}
