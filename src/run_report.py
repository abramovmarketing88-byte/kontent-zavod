"""Persist a per-run diagnostic report (no secrets) for debugging."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import Settings

logger = logging.getLogger(__name__)

SECRET_ENV_KEYS = (
    "API_KEY",
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "CURSOR_API",
    "ELEVENLABS",
    "HEYGEN",
    "OPENAI",
    "OPENROUTER",
    "YOUTUBE",
    "PEXELS",
    "TELEGRAM_BOT",
    "IG_PASSWORD",
)

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|authorization|bearer)\s*[:=]\s*\S+"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=***", text)


@dataclass
class RunReport:
    settings: Settings
    run_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    trigger_id: str = ""
    status: str = "running"
    stages: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    processed: int = 0
    started_at: str = field(default_factory=_utc_now)
    finished_at: str = ""
    _file_handler: logging.Handler | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.trigger_id = (
            os.getenv("RUN_ONCE_TRIGGER_ID", "").strip()
            or self._read_trigger_id()
        )
        self.reports_dir = self.settings.root / "reports"
        self.history_dir = self.reports_dir / "history"
        self.logs_dir = self.settings.root / "logs" / "runs"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._attach_file_logger()

    def _read_trigger_id(self) -> str:
        path = self.settings.root / "triggers" / "run-once.id"
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _attach_file_logger(self) -> None:
        log_path = self.logs_dir / f"{self.run_id}.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
        self._file_handler = handler
        self.log_file = log_path

    def stage(self, name: str, detail: str = "") -> None:
        entry = {"name": name, "at": _utc_now(), "detail": detail[:500]}
        self.stages.append(entry)
        logger.info("stage=%s %s", name, detail)

    def add_source(self, meta: Any) -> None:
        self.sources.append(
            {
                "source_id": getattr(meta, "source_id", ""),
                "platform": getattr(meta, "platform", ""),
                "title": getattr(meta, "title", ""),
                "url": getattr(meta, "url", ""),
                "views": getattr(meta, "views", 0),
                "score": getattr(meta, "score", 0),
            }
        )

    def fail(self, exc: BaseException) -> None:
        if self.status != "failed":
            self.status = "failed"
            self.errors.append(_redact(f"{type(exc).__name__}: {exc}"))
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                self.errors.append(_redact(tb[-4000:]))
            self.finished_at = _utc_now()
        self.write()

    def complete(self, processed: int, *, empty: bool = False) -> None:
        self.processed = processed
        self.status = "empty" if empty else "ok"
        self.finished_at = _utc_now()
        self.write()

    def _settings_snapshot(self) -> dict[str, Any]:
        s = self.settings
        return {
            "renderer": s.renderer,
            "max_videos_per_run": s.max_videos_per_run,
            "whisper_model": s.whisper_model,
            "transcribe_backend": s.transcribe_backend,
            "target_duration_min": s.target_duration_min,
            "target_duration_max": s.target_duration_max,
            "telegram_notify": s.telegram_notify,
            "heygen_intro_sec": s.heygen_intro_sec,
            "has_cursor_key": bool(s.cursor_api_key),
            "has_elevenlabs_key": bool(s.elevenlabs_api_key),
            "has_youtube_key": bool(s.youtube_api_key),
            "has_pexels_key": bool(s.pexels_api_key),
            "has_llm_key": bool(s.llm_api_key),
            "has_heygen_key": bool(s.heygen_api_key),
            "has_heygen_avatar": bool(s.heygen_avatar_id),
            "has_telegram_token": bool(s.telegram_bot_token),
            "has_telegram_chat": bool(s.telegram_owner_chat_id),
            "llm_model": s.llm_model,
            "llm_base_url": s.llm_base_url,
            "niche_queries": list(s.niche.search_queries),
            "min_views": s.niche.min_views,
            "ig_hashtags": list(s.instagram.hashtags),
        }

    def _tail_log(self, limit: int = 80) -> str:
        try:
            lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-limit:])

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trigger_id": self.trigger_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "processed": self.processed,
            "stages": self.stages,
            "sources": self.sources,
            "errors": self.errors,
            "settings": self._settings_snapshot(),
            "log_file": str(self.log_file),
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        lines = [
            f"# Run report `{d['run_id']}`",
            "",
            f"- status: **{d['status']}**",
            f"- trigger: `{d['trigger_id'] or '—'}`",
            f"- started: {d['started_at']}",
            f"- finished: {d['finished_at'] or '—'}",
            f"- processed: {d['processed']}",
            f"- log_file: `{d['log_file']}`",
            "",
            "## Settings (no secrets)",
            "```json",
            json.dumps(d["settings"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Stages",
        ]
        if d["stages"]:
            for st in d["stages"]:
                detail = f" — {st['detail']}" if st.get("detail") else ""
                lines.append(f"- `{st['at']}` **{st['name']}**{detail}")
        else:
            lines.append("- (none)")

        lines.extend(["", "## Sources"])
        if d["sources"]:
            for src in d["sources"]:
                lines.append(
                    f"- [{src.get('platform')}] {src.get('title')} "
                    f"({src.get('views')} views) {src.get('url')}"
                )
        else:
            lines.append("- (none)")

        lines.extend(["", "## Errors"])
        if d["errors"]:
            lines.append("```")
            lines.extend(d["errors"])
            lines.append("```")
        else:
            lines.append("- (none)")

        tail = self._tail_log()
        lines.extend(["", "## Log tail", "```"])
        lines.append(_redact(tail) if tail else "(empty)")
        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    def write(self) -> Path:
        self._detach_file_logger()
        md = self.to_markdown()
        data = self.to_dict()
        data["log_tail"] = _redact(self._tail_log(120))

        last_md = self.reports_dir / "last-run.md"
        last_json = self.reports_dir / "last-run.json"
        hist_md = self.history_dir / f"{self.run_id}.md"
        hist_json = self.history_dir / f"{self.run_id}.json"

        last_md.write_text(md, encoding="utf-8")
        last_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        hist_md.write_text(md, encoding="utf-8")
        hist_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote run report %s (%s)", last_md, self.status)
        return last_md

    def _detach_file_logger(self) -> None:
        if self._file_handler is not None:
            logging.getLogger().removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

    def telegram_summary(self, limit: int = 1500) -> str:
        icon = {"ok": "✅", "empty": "⚠️", "failed": "💥"}.get(self.status, "ℹ️")
        head = (
            f"{icon} Отчёт прогона `{self.run_id}`\n"
            f"status={self.status} processed={self.processed}\n"
        )
        if self.errors:
            head += f"error: {self.errors[0][:300]}\n"
        head += "\nЛог (хвост):\n"
        tail = _redact(self._tail_log(40))
        budget = max(0, limit - len(head) - 20)
        if len(tail) > budget:
            tail = "…\n" + tail[-budget:]
        return head + tail
