"""Freeform topic inbox — make a Reels from an idea, no source video."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path

from src.config import Settings
from src.db import Database
from src.models import SourceMeta

logger = logging.getLogger(__name__)


def topic_brief_path(inbox_dir: Path, source_id: str) -> Path:
    return inbox_dir / "processed" / f"{source_id}.txt"


class TopicDiscoverer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.topic_file = settings.inbox_dir / "topic.txt"
        self.processed_dir = settings.inbox_dir / "processed"

    def discover(self) -> list[SourceMeta]:
        if not self.topic_file.exists():
            return []
        raw = self.topic_file.read_text(encoding="utf-8")
        lines = [
            ln.strip()
            for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        text = "\n".join(lines).strip()
        if not text:
            return []

        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        source_id = f"topic_{digest}"
        if self.db.should_skip_discovery(source_id):
            logger.info("Topic already processed: %s", source_id)
            return []

        title = lines[0][:120]
        meta = SourceMeta(
            source_id=source_id,
            url=f"topic://{source_id}",
            title=title,
            views=0,
            channel="topic",
            platform="topic",
            query="inbox/topic.txt",
            score=2e9,
            duration_sec=35.0,
        )

        self.processed_dir.mkdir(parents=True, exist_ok=True)
        topic_brief_path(self.settings.inbox_dir, source_id).write_text(
            text + "\n", encoding="utf-8"
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (self.processed_dir / f"topic_{stamp}.txt").write_text(text + "\n", encoding="utf-8")
        self.topic_file.write_text("", encoding="utf-8")
        logger.info("Topic queued: %s (%s)", source_id, title)
        return [meta]
