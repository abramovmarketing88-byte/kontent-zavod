"""Download audio and transcribe."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import yt_dlp

from src.analyze.transcriber import transcribe_audio
from src.config import Settings
from src.ffmpeg_bin import get_ffmpeg
from src.models import SourceMeta, TranscriptResult

logger = logging.getLogger(__name__)


class Analyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(self, job_path: Path, meta: SourceMeta) -> TranscriptResult:
        audio_path = job_path / "source_audio.wav"
        if not audio_path.exists():
            self._download_audio(meta.url, audio_path)

        transcript = transcribe_audio(self.settings, audio_path)
        logger.info(
            "Transcribed %s (%d chars, backend=%s)",
            meta.source_id,
            len(transcript.text),
            self.settings.transcribe_backend,
        )
        return transcript

    def _download_audio(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stem = output_path.with_suffix("")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{stem}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        if "youtube.com" in url or "youtu.be" in url:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        candidates = [
            p for p in output_path.parent.glob(f"{stem.name}.*") if p.suffix != ".wav"
        ]
        if not candidates:
            candidates = list(output_path.parent.glob(f"{stem.name}.*"))
        if not candidates:
            raise FileNotFoundError(f"Audio not downloaded for {url}")

        downloaded = max(candidates, key=lambda p: p.stat().st_mtime)
        if downloaded == output_path:
            return

        subprocess.run(
            [
                get_ffmpeg(),
                "-y",
                "-i",
                str(downloaded),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        if downloaded != output_path:
            downloaded.unlink(missing_ok=True)
