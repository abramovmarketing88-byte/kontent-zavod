"""Shared data models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    REWRITTEN = "rewritten"
    VOICED = "voiced"
    RENDERED = "rendered"
    PUBLISHED = "published"
    FAILED = "failed"


class ShotSpec(BaseModel):
    keywords: list[str]
    duration_sec: float = 3.0


class RemakeSpec(BaseModel):
    hook: str
    script: str
    shots: list[ShotSpec]
    caption: str
    hashtags: list[str]
    title: str
    avatar_intro_sec: float | None = None


class SourceMeta(BaseModel):
    source_id: str
    url: str
    title: str
    views: int = 0
    published_at: str = ""
    channel: str = ""
    duration_sec: float = 0.0
    score: float = 0.0
    query: str = ""


class TranscriptResult(BaseModel):
    text: str
    language: str = "ru"
    segments: list[dict[str, Any]] = Field(default_factory=list)


class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class VoiceResult(BaseModel):
    audio_path: str
    words: list[WordTiming]
    duration_sec: float


def today_output_dir(output_root: str) -> str:
    return f"{output_root}/{datetime.now().strftime('%Y-%m-%d')}"
