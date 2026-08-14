"""Free TTS fallback via Microsoft Edge (works without API key)."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from src.ffmpeg_bin import probe_duration
from src.models import RemakeSpec, VoiceResult, WordTiming

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "ru-RU-DmitryNeural"


async def _synthesize_async(text: str, output_path: Path, voice: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


def synthesize_edge(
    job_path: Path,
    remake: RemakeSpec,
    voice: str = DEFAULT_VOICE,
) -> VoiceResult:
    output_path = job_path / "voice.mp3"
    asyncio.run(_synthesize_async(remake.script.strip(), output_path, voice))

    duration = probe_duration(output_path)
    words = _estimate_word_timings(remake.script, duration)
    logger.info("Edge TTS synthesized: %.1fs, %d words", duration, len(words))
    return VoiceResult(
        audio_path=str(output_path),
        words=words,
        duration_sec=duration,
    )


def _estimate_word_timings(script: str, duration: float) -> list[WordTiming]:
    words = [w for w in re.split(r"\s+", script.strip()) if w]
    if not words or duration <= 0:
        return []

    slice_dur = duration / len(words)
    timings: list[WordTiming] = []
    t = 0.0
    for word in words:
        timings.append(WordTiming(word=word, start=t, end=t + slice_dur * 0.95))
        t += slice_dur
    return timings
