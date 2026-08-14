"""Download audio and transcribe."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from src.analyze.transcriber import transcribe_audio
from src.config import Settings
from src.ffmpeg_bin import get_ffmpeg
from src.models import SourceMeta, TranscriptResult

logger = logging.getLogger(__name__)

# YouTube often returns 503 on one client; rotate clients + backoff.
_YOUTUBE_CLIENT_SETS = (
    ["android", "ios"],
    ["android_creator", "ios"],
    ["tv", "android"],
    ["web"],
)


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
        is_youtube = "youtube.com" in url or "youtu.be" in url

        last_error: Exception | None = None
        client_sets = _YOUTUBE_CLIENT_SETS if is_youtube else [None]

        for attempt, clients in enumerate(client_sets, start=1):
            ydl_opts: dict = {
                "format": "bestaudio/best",
                "outtmpl": f"{stem}.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "retries": 10,
                "fragment_retries": 10,
                "retry_sleep_functions": {
                    "http": lambda n: min(2 ** n, 30),
                    "fragment": lambda n: min(2 ** n, 30),
                },
                "socket_timeout": 30,
                # Prefer env HTTP(S)_PROXY from docker-compose (mihomo).
                "nocheckcertificate": False,
            }
            if clients:
                ydl_opts["extractor_args"] = {
                    "youtube": {"player_client": list(clients)}
                }
                logger.info(
                    "yt-dlp attempt %d/%d clients=%s url=%s",
                    attempt,
                    len(client_sets),
                    ",".join(clients),
                    url,
                )
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                last_error = None
                break
            except DownloadError as exc:
                last_error = exc
                logger.warning("yt-dlp download failed (attempt %d): %s", attempt, exc)
                time.sleep(min(2 * attempt, 8))
            except Exception as exc:
                last_error = exc
                logger.warning("yt-dlp unexpected error (attempt %d): %s", attempt, exc)
                time.sleep(min(2 * attempt, 8))

        if last_error is not None:
            raise last_error

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
