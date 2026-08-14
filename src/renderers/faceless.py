"""Faceless ffmpeg renderer — stock B-roll + karaoke captions."""

from __future__ import annotations

import logging
from pathlib import Path

from src.assemble.captions import build_karaoke_ass
from src.assemble.ffmpeg import concat_clips, mux_final, normalize_clip, probe_duration
from src.models import RemakeSpec, VoiceResult

logger = logging.getLogger(__name__)


class FacelessFfmpegRenderer:
    def render(
        self,
        job_path: Path,
        remake: RemakeSpec,
        voice: VoiceResult,
        shot_clips: list[Path],
    ) -> Path:
        work = job_path / "render"
        work.mkdir(exist_ok=True)

        total_duration = max(voice.duration_sec, 5.0)
        n_shots = max(len(shot_clips), 1)
        per_shot = total_duration / n_shots

        normalized: list[Path] = []
        for idx, clip in enumerate(shot_clips):
            out = work / f"norm_{idx:02d}.mp4"
            normalize_clip(clip, out, per_shot)
            normalized.append(out)

        if not normalized:
            raise RuntimeError("No clips to render")

        # Extend if audio longer than video
        video_duration = sum(probe_duration(c) for c in normalized)
        if video_duration < total_duration and normalized:
            extra_needed = total_duration - video_duration
            last = normalized[-1]
            extra = work / "norm_extra.mp4"
            normalize_clip(shot_clips[-1], extra, extra_needed)
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
        mux_final(concat_path, Path(voice.audio_path), ass_path, final_path)
        logger.info("Rendered faceless video: %s", final_path)
        return final_path
