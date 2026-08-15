"""Discovery orchestration."""

from __future__ import annotations

import logging

from src.config import Settings
from src.db import Database
from src.discover.inbox import InboxDiscoverer
from src.discover.instagram import InstagramDiscoverer
from src.discover.topic import TopicDiscoverer
from src.discover.youtube import YouTubeDiscoverer
from src.models import SourceMeta

logger = logging.getLogger(__name__)


def discover_sources(settings: Settings, db: Database) -> list[SourceMeta]:
    reclaimed = db.reclaim_stale()
    topics = TopicDiscoverer(settings, db).discover()
    inbox = InboxDiscoverer(settings, db).discover()
    youtube = YouTubeDiscoverer(settings, db).discover()
    instagram = InstagramDiscoverer(settings, db).discover()
    # Reclaimed / previously failed URLs may not appear in today's YouTube top-N.
    # Pull them from DB so empty search pools still have work.
    retries = db.list_retryable_failed(
        limit=max(settings.max_videos_per_run * 5, 10)
    )
    merged: dict[str, SourceMeta] = {}
    for meta in topics + inbox + youtube + instagram + retries:
        existing = merged.get(meta.source_id)
        if not existing or meta.score > existing.score:
            merged[meta.source_id] = meta
    result = sorted(merged.values(), key=lambda m: m.score, reverse=True)
    logger.info(
        "Discovered %d source(s) (topic=%d inbox=%d yt=%d ig=%d retry=%d reclaimed=%d)",
        len(result),
        len(topics),
        len(inbox),
        len(youtube),
        len(instagram),
        len(retries),
        reclaimed,
    )
    return result
