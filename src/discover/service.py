"""Discovery orchestration."""

from __future__ import annotations

import logging

from src.config import Settings
from src.db import Database
from src.discover.inbox import InboxDiscoverer
from src.discover.instagram import InstagramDiscoverer
from src.discover.youtube import YouTubeDiscoverer
from src.models import SourceMeta

logger = logging.getLogger(__name__)


def discover_sources(settings: Settings, db: Database) -> list[SourceMeta]:
    inbox = InboxDiscoverer(settings, db).discover()
    youtube = YouTubeDiscoverer(settings, db).discover()
    instagram = InstagramDiscoverer(settings, db).discover()
    merged: dict[str, SourceMeta] = {}
    for meta in inbox + youtube + instagram:
        existing = merged.get(meta.source_id)
        if not existing or meta.score > existing.score:
            merged[meta.source_id] = meta
    result = sorted(merged.values(), key=lambda m: m.score, reverse=True)
    logger.info("Discovered %d new source(s)", len(result))
    return result
