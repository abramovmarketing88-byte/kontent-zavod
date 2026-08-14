"""Pexels stock video fetcher."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

from src.config import Settings
from src.models import RemakeSpec

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.pexels.com/videos/search"
MIN_HEIGHT = 1080


class PexelsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.headers = {"Authorization": settings.pexels_api_key}

    def download_shots(
        self,
        job_path: Path,
        remake: RemakeSpec,
        *,
        refresh: bool = False,
    ) -> list[Path]:
        if not self.settings.pexels_api_key:
            raise RuntimeError("PEXELS_API_KEY not set")

        shots_dir = job_path / "shots"
        if refresh and shots_dir.exists():
            for old in shots_dir.glob("*.mp4"):
                old.unlink()

        shots_dir.mkdir(exist_ok=True)
        paths: list[Path] = []

        for idx, shot in enumerate(remake.shots):
            query = " ".join(shot.keywords) if shot.keywords else "cinematic business vertical"
            clip_path = shots_dir / f"shot_{idx:02d}.mp4"
            if clip_path.exists() and not refresh:
                paths.append(clip_path)
                continue
            pick = _pick_index(query, idx)
            self._download_one(query, clip_path, pick_index=pick)
            paths.append(clip_path)

        if not paths:
            fallback = shots_dir / "shot_00.mp4"
            self._download_one("cinematic office vertical 4k", fallback, pick_index=0)
            paths.append(fallback)

        return paths

    def _download_one(self, query: str, dest: Path, *, pick_index: int = 0) -> None:
        videos = self._search(query, orientation="portrait")
        if not videos:
            videos = self._search(query, orientation="landscape")

        if not videos:
            raise RuntimeError(f"No Pexels videos for query: {query}")

        videos = sorted(
            videos,
            key=lambda v: (
                -(v.get("height") or 0),
                -(v.get("width") or 0),
            ),
        )
        pick_index = pick_index % len(videos)
        video = videos[pick_index]
        file_url = _best_file_url(video.get("video_files", []))
        if not file_url:
            raise RuntimeError(f"No suitable file for Pexels video {video.get('id')}")

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            content = client.get(file_url).content
        dest.write_bytes(content)
        logger.info(
            "Downloaded Pexels clip: %s (id=%s, pick=%d) -> %s",
            query,
            video.get("id"),
            pick_index,
            dest.name,
        )

    def _search(self, query: str, *, orientation: str) -> list[dict]:
        params = {
            "query": query,
            "orientation": orientation,
            "size": "large",
            "per_page": 20,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(SEARCH_URL, headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json().get("videos", [])


def _pick_index(query: str, shot_idx: int) -> int:
    """Spread picks across results — avoid always grabbing the first blurry hit."""
    digest = hashlib.sha256(f"{query}:{shot_idx}".encode()).hexdigest()
    return int(digest[:2], 16) % 5


def _best_file_url(files: list[dict]) -> str | None:
    if not files:
        return None

    portrait = [
        f
        for f in files
        if (f.get("height") or 0) >= (f.get("width") or 0)
        and (f.get("height") or 0) >= MIN_HEIGHT
    ]
    pool = portrait or [
        f for f in files if (f.get("height") or 0) >= (f.get("width") or 0)
    ] or files

    best = max(pool, key=lambda f: (f.get("height") or 0) * (f.get("width") or 0))
    return best.get("link")
