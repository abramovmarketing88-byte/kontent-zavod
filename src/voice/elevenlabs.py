"""ElevenLabs TTS with word-level timestamps."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import httpx

from src.config import Settings
from src.models import RemakeSpec, VoiceResult, WordTiming
from src.voice.edge_tts_fallback import synthesize_edge

logger = logging.getLogger(__name__)

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"


class ElevenLabsVoice:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        voice_cfg_path = settings.brand_dir / "voice.json"
        self.voice_cfg = json.loads(voice_cfg_path.read_text(encoding="utf-8"))

    def synthesize(self, job_path: Path, remake: RemakeSpec) -> VoiceResult:
        if not self.settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        voice_id = self.settings.elevenlabs_voice_id or self.voice_cfg.get("voice_id")
        if not voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID not set")

        text = remake.script.strip()
        payload = {
            "text": text,
            "model_id": self.voice_cfg.get("model_id", "eleven_multilingual_v2"),
            "voice_settings": {
                "stability": self.voice_cfg.get("stability", 0.5),
                "similarity_boost": self.voice_cfg.get("similarity_boost", 0.75),
                "speed": self.voice_cfg.get("speed", 1.0),
            },
        }
        headers = {
            "xi-api-key": self.settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        }

        url = TTS_URL.format(voice_id=voice_id)
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ElevenLabs failed (%s) — using Edge TTS fallback", exc)
            return synthesize_edge(job_path, remake)

        audio_path = job_path / "voice.mp3"
        audio_bytes = base64.b64decode(data["audio_base64"])
        audio_path.write_bytes(audio_bytes)

        alignment = data.get("normalized_alignment") or data.get("alignment") or {}
        words = _alignment_to_words(alignment)
        duration = words[-1].end if words else 0.0

        timings_path = job_path / "word_timings.json"
        timings_path.write_text(
            json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Voice synthesized (ElevenLabs %s): %.1fs, %d words",
            voice_id,
            duration,
            len(words),
        )
        return VoiceResult(
            audio_path=str(audio_path),
            words=words,
            duration_sec=duration,
        )


def _alignment_to_words(alignment: dict) -> list[WordTiming]:
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    if not chars:
        return []

    words: list[WordTiming] = []
    current = ""
    word_start: float | None = None
    word_end = 0.0

    for ch, start, end in zip(chars, starts, ends):
        if ch.isspace():
            if current:
                words.append(
                    WordTiming(word=current, start=word_start or 0.0, end=word_end)
                )
                current = ""
                word_start = None
            continue
        if not current:
            word_start = start
        current += ch
        word_end = end

    if current:
        words.append(WordTiming(word=current, start=word_start or 0.0, end=word_end))

    return words
