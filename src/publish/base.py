"""Shared publish contracts for multi-platform auto-posting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

PublishStatus = Literal["ok", "skipped", "failed"]


@dataclass
class PublishMeta:
    """Caption/title payload shared across platforms."""

    title: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    source_id: str = ""
    video_path: Path | None = None

    def description(self, *, max_len: int = 4000) -> str:
        tags = " ".join(h if h.startswith("#") else f"#{h}" for h in self.hashtags)
        text = f"{self.caption}\n\n{tags}".strip() if tags else (self.caption or self.title)
        return text[:max_len]

    def title_or_stem(self, fallback: str = "Reel") -> str:
        if self.title.strip():
            return self.title.strip()[:100]
        if self.caption.strip():
            return self.caption.splitlines()[0].strip()[:100]
        return fallback[:100]


@dataclass
class PublishResult:
    platform: str
    status: PublishStatus
    url: str = ""
    error: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, platform: str, url: str = "", **detail: Any) -> PublishResult:
        return cls(platform=platform, status="ok", url=url, detail=detail)

    @classmethod
    def skipped(cls, platform: str, reason: str) -> PublishResult:
        return cls(platform=platform, status="skipped", error=reason)

    @classmethod
    def failed(cls, platform: str, error: str, **detail: Any) -> PublishResult:
        return cls(platform=platform, status="failed", error=str(error)[:800], detail=detail)

    def line(self) -> str:
        if self.status == "ok":
            extra = f" {self.url}" if self.url else ""
            return f"✅ {self.platform}{extra}"
        if self.status == "skipped":
            return f"⏭ {self.platform}: {self.error or 'skipped'}"
        return f"❌ {self.platform}: {self.error or 'failed'}"


class Publisher(Protocol):
    name: str

    def enabled(self, settings: Any) -> bool: ...

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult: ...
