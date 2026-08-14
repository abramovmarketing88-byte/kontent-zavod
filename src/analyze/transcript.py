"""Download audio and transcribe with faster-whisper."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import yt_dlp
from faster_whisper import WhisperModel

from src.ffmpeg_bin import get_ffmpeg
from src.config import Settings
from src.models import SourceMeta, TranscriptResult

logger = logging.getLogger(__name__)


class Analyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: WhisperModel | None = None

    @property
    def model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self.settings.whisper_model,
                device="cpu",
                compute_type="int8",
            )
        return self._model

    def analyze(self, job_path: Path, meta: SourceMeta) -> TranscriptResult:
        audio_path = job_path / "source_audio.wav"
        if not audio_path.exists():
            self._download_audio(meta.url, audio_path)

        segments_iter, info = self.model.transcribe(
            str(audio_path),
            language="ru",
            vad_filter=True,
        )
        segments = []
        parts: list[str] = []
        for seg in segments_iter:
            segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                }
            )
            parts.append(seg.text.strip())

        transcript = TranscriptResult(
            text=" ".join(parts).strip(),
            language=info.language or "ru",
            segments=segments,
        )
        logger.info(
            "Transcribed %s (%d chars)",
            meta.source_id,
            len(transcript.text),
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
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
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
