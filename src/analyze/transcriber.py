"""Pluggable transcription backends."""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import Settings
from src.models import TranscriptResult

logger = logging.getLogger(__name__)


def transcribe_audio(settings: Settings, audio_path: Path) -> TranscriptResult:
    backend = settings.transcribe_backend.lower()
    if backend == "openai":
        return _transcribe_openai(settings, audio_path)
    return _transcribe_faster_whisper(settings, audio_path)


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
