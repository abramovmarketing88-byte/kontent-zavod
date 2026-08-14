"""Renderer protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.models import RemakeSpec, VoiceResult


class Renderer(Protocol):
    def render(
        self,
        job_path: Path,
        remake: RemakeSpec,
        voice: VoiceResult,
        shot_clips: list[Path],
    ) -> Path:
        """Render final mp4 and return path."""
        ...
