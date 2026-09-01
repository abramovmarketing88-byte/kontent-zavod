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


class OrderStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"
    VOICING = "voicing"
    VISUALS = "visuals"
    RENDERING = "rendering"
    READY = "ready"
    PUBLISH_REQUESTED = "publish_requested"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentOrder(BaseModel):
    id: str
    owner_chat_id: str
    topic: str
    brief: str
    idempotency_key: str = ""
    status: OrderStatus
    current_stage: str = "queued"
    source_id: str = ""
    renderer: str = "auto"
    output_path: str = ""
    status_message_id: int | None = None
    revision_instruction: str = ""
    draft_version: int = 0
    error_code: str = ""
    error_user_text: str = ""
    retry_count: int = 0
    created_at: str = ""
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""


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
    platform: str = "youtube"
    order_id: str = ""


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
