"""Pluggable transcription backends."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.config import Settings
from src.models import TranscriptResult

logger = logging.getLogger(__name__)


def transcribe_audio(
    settings: Settings,
    audio_path: Path,
    *,
    source_url: str = "",
) -> TranscriptResult:
    backend = settings.transcribe_backend.lower()
    if backend == "youtube_captions":
        return _transcribe_youtube_captions(source_url)

    if backend == "openai":
        try:
            return _transcribe_openai(settings, audio_path)
        except RuntimeError as exc:
            if "OPENAI_API_KEY" in str(exc) and _is_youtube_url(source_url):
                logger.warning(
                    "OPENAI_API_KEY missing — falling back to YouTube captions"
                )
                return _transcribe_youtube_captions(source_url)
            raise

    try:
        return _transcribe_faster_whisper(settings, audio_path)
    except Exception as exc:
        if _is_youtube_url(source_url):
            logger.warning("faster-whisper failed (%s) — trying YouTube captions", exc)
            return _transcribe_youtube_captions(source_url)
        raise


def _is_youtube_url(url: str) -> bool:
    return bool(url) and ("youtube.com" in url or "youtu.be" in url)


def _transcribe_faster_whisper(settings: Settings, audio_path: Path) -> TranscriptResult:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        settings.whisper_model,
        device="cpu",
        compute_type="int8",
    )
    segments_iter, info = model.transcribe(
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

    return TranscriptResult(
        text=" ".join(parts).strip(),
        language=info.language or "ru",
        segments=segments,
    )


def _transcribe_openai(settings: Settings, audio_path: Path) -> TranscriptResult:
    import os

    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required for TRANSCRIBE_BACKEND=openai")

    client = OpenAI(api_key=api_key)
    with audio_path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model=os.getenv("OPENAI_WHISPER_MODEL", "whisper-1"),
            file=audio_file,
            language="ru",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    parts: list[str] = []
    for seg in getattr(response, "segments", []) or []:
        text = (seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", "")).strip()
        start = seg.get("start") if isinstance(seg, dict) else getattr(seg, "start", 0.0)
        end = seg.get("end") if isinstance(seg, dict) else getattr(seg, "end", 0.0)
        segments.append({"start": start, "end": end, "text": text})
        if text:
            parts.append(text)

    text = " ".join(parts).strip() or getattr(response, "text", "")
    language = getattr(response, "language", "ru") or "ru"
    logger.info("OpenAI Whisper transcribed %d chars", len(text))
    return TranscriptResult(text=text, language=language, segments=segments)


def _transcribe_youtube_captions(url: str) -> TranscriptResult:
    """Fallback: pull auto/manual captions via yt-dlp (YouTube only)."""
    if not _is_youtube_url(url):
        raise RuntimeError("YouTube captions fallback requires a YouTube URL")

    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ru", "en"],
        "subtitlesformat": "vtt",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    text = _pick_caption_text(info)
    if not text:
        raise RuntimeError(f"No captions available for {url}")

    logger.info("YouTube captions transcribed %d chars", len(text))
    return TranscriptResult(text=text, language="ru", segments=[])


def _pick_caption_text(info: dict) -> str:
    for key in ("subtitles", "automatic_captions"):
        tracks = info.get(key) or {}
        for lang in ("ru", "en"):
            entries = tracks.get(lang) or []
            for entry in entries:
                if entry.get("ext") in ("vtt", "srv3", "ttml", "json3"):
                    data = _download_caption(entry.get("url", ""))
                    if data:
                        return _strip_vtt(data)
    return ""


def _download_caption(url: str) -> str:
    if not url:
        return ""
    import httpx

    try:
        resp = httpx.get(url, timeout=60.0)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Caption download failed: %s", exc)
        return ""


def _strip_vtt(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)
    # Deduplicate consecutive identical lines (common in auto-captions)
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return " ".join(out).strip()
