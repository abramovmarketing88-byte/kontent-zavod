"""Instagram Reels discovery via instaloader."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import InstagramNicheConfig, Settings
from src.db import Database
from src.discover.youtube import _score
from src.models import SourceMeta

logger = logging.getLogger(__name__)


class InstagramDiscoverer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.niche = settings.instagram

    def discover(self, limit: int | None = None) -> list[SourceMeta]:
        if not self.niche.hashtags and not self.niche.accounts:
            return []

        username = os.getenv("IG_USERNAME", "")
        password = os.getenv("IG_PASSWORD", "")
        session_file = os.getenv("IG_SESSION_FILE", "")
        if not username and not session_file:
            logger.warning(
                "IG_USERNAME or IG_SESSION_FILE not set — skipping Instagram discovery"
            )
            return []

        try:
            import instaloader
        except ImportError:
            logger.warning("instaloader not installed — skipping Instagram discovery")
            return []

        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
        )

        try:
            if session_file and Path(session_file).exists():
                loader.load_session_from_file(username or "session", session_file)
            elif username and password:
                loader.login(username, password)
                if session_file:
                    loader.save_session_to_file(session_file)
            else:
                logger.warning("IG credentials incomplete — skipping Instagram discovery")
                return []
        except Exception as exc:
            logger.error("Instagram login failed: %s", exc)
            return []

        candidates: dict[str, SourceMeta] = {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.niche.max_age_days)

        for hashtag in self.niche.hashtags:
            self._collect_from_hashtag(loader, hashtag, cutoff, candidates)

        for account in self.niche.accounts:
            self._collect_from_profile(loader, account, cutoff, candidates)

        ranked = sorted(candidates.values(), key=lambda m: m.score, reverse=True)
        cap = limit or self.settings.max_videos_per_run
        return ranked[:cap]

    def _collect_from_hashtag(
        self,
        loader,
        hashtag: str,
        cutoff: datetime,
        candidates: dict[str, SourceMeta],
    ) -> None:
        import instaloader

        tag = hashtag.lstrip("#")
        try:
            hashtag_obj = instaloader.Hashtag.from_name(loader.context, tag)
        except Exception as exc:
            logger.warning("Instagram hashtag %s failed: %s", tag, exc)
            return

        for post in hashtag_obj.get_posts():
            self._maybe_add_post(post, f"#{tag}", cutoff, candidates)

    def _collect_from_profile(
        self,
        loader,
        account: str,
        cutoff: datetime,
        candidates: dict[str, SourceMeta],
    ) -> None:
        import instaloader

        name = account.lstrip("@")
        try:
            profile = instaloader.Profile.from_username(loader.context, name)
        except Exception as exc:
            logger.warning("Instagram profile %s failed: %s", name, exc)
            return

        for post in profile.get_posts():
            if not post.is_video:
                continue
            self._maybe_add_post(post, f"@{name}", cutoff, candidates)

    def _maybe_add_post(
        self,
        post,
        query: str,
        cutoff: datetime,
        candidates: dict[str, SourceMeta],
    ) -> None:
        if not post.is_video:
            return

        shortcode = post.shortcode
        if self.db.should_skip_discovery(shortcode):
            return

        post_date = post.date_utc.replace(tzinfo=timezone.utc)
        if post_date < cutoff:
            return

        views = int(getattr(post, "video_view_count", 0) or getattr(post, "play_count", 0) or 0)
        if views < self.niche.min_views:
            return

        duration = float(getattr(post, "video_duration", 0) or 0)
        if duration <= 0 or duration > self.niche.max_duration_sec:
            return

        published = post_date.isoformat()
        caption = (post.caption or "").strip()
        title = caption.split("\n", 1)[0][:120] if caption else f"Reel {shortcode}"

        meta = SourceMeta(
            source_id=shortcode,
            url=f"https://www.instagram.com/reel/{shortcode}/",
            title=title,
            views=views,
            published_at=published,
            channel=post.owner_username or "",
            duration_sec=duration,
            score=_score(views, published),
            query=query,
            platform="instagram",
        )
        existing = candidates.get(shortcode)
        if not existing or meta.score > existing.score:
            candidates[shortcode] = meta
