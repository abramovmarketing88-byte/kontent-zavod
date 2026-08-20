"""Pexels stock video fetcher with local ffmpeg placeholder fallback."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

import httpx

from src.config import Settings
from src.ffmpeg_bin import get_ffmpeg
from src.models import RemakeSpec
from src.visuals.broll_query import enhance_broll_query, query_variants

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.pexels.com/videos/search"
MIN_HEIGHT = 1080
PER_PAGE = 40
PLACEHOLDER_COLORS = ("#1a1a2e", "#16213e", "#0f3460", "#533483", "#2c3e50")


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
        topic: str = "",
    ) -> list[Path]:
        shots_dir = job_path / "shots"
        if refresh and shots_dir.exists():
            for old in shots_dir.glob("*.mp4"):
                old.unlink()
        shots_dir.mkdir(parents=True, exist_ok=True)

        if not self.settings.pexels_api_key:
            logger.warning("PEXELS_API_KEY not set — generating placeholder clips")
            return self._generate_placeholders(shots_dir, remake)

        if not topic:
            topic_path = job_path / "topic.txt"
            if topic_path.exists():
                topic = topic_path.read_text(encoding="utf-8").strip().splitlines()[0]

        paths: list[Path] = []
        for idx, shot in enumerate(remake.shots):
            keywords = shot.keywords or []
            query = enhance_broll_query(keywords, topic=topic, shot_index=idx)
            clip_path = shots_dir / f"shot_{idx:02d}.mp4"
            if clip_path.exists() and not refresh:
                paths.append(clip_path)
                continue
            pick = _pick_index(query, idx)
            try:
                self._download_one(query, clip_path, pick_index=pick, topic=topic)
                paths.append(clip_path)
            except Exception as exc:
                logger.warning("Pexels shot %d failed (%s) — placeholder", idx, exc)
                paths.append(
                    self._make_placeholder(
                        shots_dir / f"shot_{idx:02d}.mp4",
                        max(shot.duration_sec, 3.0),
                        PLACEHOLDER_COLORS[idx % len(PLACEHOLDER_COLORS)],
                    )
                )

        if not paths:
            fallback = shots_dir / "shot_00.mp4"
            try:
                self._download_one(
                    enhance_broll_query(["cinematic office"], topic=topic, shot_index=0),
                    fallback,
                    pick_index=0,
                    topic=topic,
                )
            except Exception as exc:
                logger.warning("Pexels fallback failed (%s) — placeholder", exc)
                self._make_placeholder(fallback, 5.0, PLACEHOLDER_COLORS[0])
            paths.append(fallback)

        return paths

    def _generate_placeholders(self, shots_dir: Path, remake: RemakeSpec) -> list[Path]:
        shots = remake.shots or []
        if not shots:
            return [
                self._make_placeholder(
                    shots_dir / "shot_00.mp4", 5.0, PLACEHOLDER_COLORS[0]
                )
            ]
        paths: list[Path] = []
        for idx, shot in enumerate(shots):
            paths.append(
                self._make_placeholder(
                    shots_dir / f"shot_{idx:02d}.mp4",
                    max(getattr(shot, "duration_sec", 3.0) or 3.0, 3.0),
                    PLACEHOLDER_COLORS[idx % len(PLACEHOLDER_COLORS)],
                )
            )
        return paths

    def _make_placeholder(self, dest: Path, duration: float, color: str) -> Path:
        color = color.lstrip("#")
        cmd = [
            get_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color}:s=1080x1920:d={duration:.2f}:r=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            f"{duration:.2f}",
            str(dest),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info("Placeholder clip %.1fs -> %s", duration, dest.name)
        return dest

    def _download_one(
        self,
        query: str,
        dest: Path,
        *,
        pick_index: int = 0,
        topic: str = "",
    ) -> None:
        last_error: Exception | None = None
        for variant in query_variants(query, topic=topic):
            try:
                videos = self._search(variant, orientation="portrait")
                if not videos:
                    videos = self._search(variant, orientation="landscape")
                if not videos:
                    continue
                video = _pick_video(videos, pick_index)
                file_url = _best_file_url(video.get("video_files", []))
                if not file_url:
                    continue
                with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                    content = client.get(file_url).content
                dest.write_bytes(content)
                logger.info(
                    "Downloaded Pexels clip: %s (id=%s, pick=%d) -> %s",
                    variant[:80],
                    video.get("id"),
                    pick_index,
                    dest.name,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.debug("Pexels variant failed %r: %s", variant[:60], exc)
        raise RuntimeError(f"No Pexels videos for query: {query}") from last_error

    def _search(self, query: str, *, orientation: str) -> list[dict]:
        params = {
            "query": query,
            "orientation": orientation,
            "size": "large",
            "per_page": PER_PAGE,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(SEARCH_URL, headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json().get("videos", [])


def _pick_index(query: str, shot_idx: int) -> int:
    """Spread picks across results — avoid always grabbing the first blurry hit."""
    digest = hashlib.sha256(f"{query}:{shot_idx}".encode()).hexdigest()
    return int(digest[:2], 16) % 8


def _pick_video(videos: list[dict], pick_index: int) -> dict:
    """Prefer tall, high-res clips; spread picks for variety."""
    ranked = sorted(
        videos,
        key=lambda v: (
            -(v.get("height") or 0),
            -(v.get("width") or 0),
            -(v.get("duration") or 0),
        ),
    )
    pick_index = pick_index % max(len(ranked), 1)
    return ranked[pick_index]


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
