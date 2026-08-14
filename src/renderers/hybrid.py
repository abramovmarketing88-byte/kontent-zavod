"""Hybrid renderer — HeyGen talking-head intro + Pexels B-roll + full voice."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.assemble.captions import build_karaoke_ass
from src.assemble.ffmpeg import (
    concat_clips,
    extract_audio_clip,
    mux_final,
    normalize_clip,
    normalize_talking_head,
    probe_duration,
    strip_audio,
)
from src.config import Settings
from src.heygen.client import HeyGenClient, HeyGenError
from src.models import RemakeSpec, VoiceResult

logger = logging.getLogger(__name__)

CACHE_FILE = "heygen_asset.json"
PENDING_FILE = "heygen_pending.json"


class HybridRenderer:
    """Avatar opens the reel; stock B-roll carries the rest."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = HeyGenClient(settings.heygen_api_key)
        self.intro_sec = settings.heygen_intro_sec

    def render(
        self,
        job_path: Path,
        remake: RemakeSpec,
        voice: VoiceResult,
        shot_clips: list[Path],
    ) -> Path:
        avatar_id = self.settings.heygen_avatar_id
        if not avatar_id:
            raise HeyGenError("HEYGEN_AVATAR_ID not set")

        if not shot_clips:
            raise RuntimeError("Hybrid renderer needs Pexels B-roll clips")

        work = job_path / "render"
        work.mkdir(exist_ok=True)

        audio_path = Path(voice.audio_path)
        total_duration = max(voice.duration_sec, 5.0)
        intro_sec = min(
            remake.avatar_intro_sec or self.intro_sec,
            total_duration * 0.45,
            total_duration - 3.0,
        )
        intro_sec = max(intro_sec, 4.0)

        intro_audio = work / "intro.mp3"
        extract_audio_clip(audio_path, intro_audio, duration=intro_sec)

        asset_id = self._audio_asset_id(job_path, intro_audio)
        heygen_raw = work / "heygen_raw.mp4"
        if not heygen_raw.exists():
            video_id = self._render_heygen(job_path, avatar_id, asset_id)
            result = self.client.wait_for_video(video_id)
            video_url = result.get("video_url") or result.get("url")
            if not video_url:
                raise HeyGenError(f"No download URL: {result}")
            self.client.download_video(video_url, heygen_raw)
            (job_path / PENDING_FILE).unlink(missing_ok=True)

        heygen_video = work / "heygen_intro.mp4"
        strip_audio(heygen_raw, heygen_video)
        normalize_talking_head(heygen_video, work / "heygen_norm.mp4")
        heygen_norm = work / "heygen_norm.mp4"
        intro_duration = probe_duration(heygen_norm)

        broll_duration = max(total_duration - intro_duration, 3.0)
        n_shots = max(len(shot_clips), 1)
        per_shot = broll_duration / n_shots

        normalized: list[Path] = [heygen_norm]
        for idx, clip in enumerate(shot_clips):
            out = work / f"broll_{idx:02d}.mp4"
            normalize_clip(clip, out, per_shot)
            normalized.append(out)

        video_duration = sum(probe_duration(c) for c in normalized)
        if video_duration < total_duration and shot_clips:
            extra = work / "broll_extra.mp4"
            normalize_clip(shot_clips[-1], extra, total_duration - video_duration)
            normalized.append(extra)

        concat_path = work / "video_no_audio.mp4"
        concat_clips(normalized, concat_path)

        ass_path = build_karaoke_ass(
            voice.words,
            work / "captions.ass",
            hook=remake.hook,
            hook_duration=2.0,
        )

        final_path = job_path / "final.mp4"
        mux_final(concat_path, audio_path, ass_path, final_path)
        logger.info(
            "Rendered hybrid video: intro %.1fs + b-roll %.1fs -> %s",
            intro_duration,
            broll_duration,
            final_path,
        )
        return final_path

    def _audio_asset_id(self, job_path: Path, audio_path: Path) -> str:
        cache_path = job_path / CACHE_FILE
        stat = audio_path.stat()
        cached: dict | None = None
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))

        cache_key = f"intro:{stat.st_size}"
        if cached and cached.get("cache_key") == cache_key and cached.get("asset_id"):
            return cached["asset_id"]

        asset_id = self.client.upload_audio(audio_path)
        cache_path.write_text(
            json.dumps(
                {"cache_key": cache_key, "size": stat.st_size, "asset_id": asset_id},
                indent=2,
            ),
            encoding="utf-8",
        )
        return asset_id

    def _render_heygen(self, job_path: Path, avatar_id: str, asset_id: str) -> str:
        pending_path = job_path / PENDING_FILE
        if pending_path.exists():
            video_id = json.loads(pending_path.read_text(encoding="utf-8")).get("video_id")
            if video_id:
                logger.info("Resuming HeyGen video %s", video_id)
                return video_id

        video_id = self.client.create_avatar_video(
            avatar_id=avatar_id,
            audio_asset_id=asset_id,
        )
        pending_path.write_text(json.dumps({"video_id": video_id}, indent=2), encoding="utf-8")
        return video_id
