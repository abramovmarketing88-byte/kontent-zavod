"""Persist a per-run diagnostic report (no secrets) for debugging.

Keeps the last N runs under reports/history/ and an index at reports/last-10.md
so Cloud Agents can always see what failed recently.
"""

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

# How many past runs to keep on disk / publish for agent diagnosis.
HISTORY_KEEP = 10

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
    r"(?i)("
    r"(?:api[_-]?key|token|password|authorization|bearer)\s*[:=]\s*\S+"
    r"|key=AIza[0-9A-Za-z_-]+"
    r"|bot\d+:[A-Za-z0-9_-]+"
    r"|sk-[A-Za-z0-9_-]{10,}"
    r"|sk_or_v1_[A-Za-z0-9_-]+"
    r"|cursor_[A-Za-z0-9_-]{10,}"
    r")"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str) -> str:
    text = _SECRET_RE.sub("***", text)
    text = re.sub(r"(?i)([?&]key=)[^&\s]+", r"\1***", text)
    text = re.sub(r"(?i)(api\.telegram\.org/bot)[^/\s]+", r"\1***", text)
    return text


class RedactFilter(logging.Filter):
    """Keep secrets out of log files / report tails."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _redact(str(v)) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        _redact(str(a)) if not isinstance(a, (int, float)) else a
                        for a in record.args
                    )
        except Exception:
            pass
        return True


def install_redact_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(f, RedactFilter) for f in root.filters):
        return
    root.addFilter(RedactFilter())


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
        self._prune_history(HISTORY_KEEP)
        self._prune_run_logs(HISTORY_KEEP)
        index_path = self.write_last10_index()
        logger.info(
            "Wrote run report %s (%s); index %s",
            last_md,
            self.status,
            index_path.name,
        )
        return last_md

    def _prune_history(self, keep: int = HISTORY_KEEP) -> None:
        """Keep only the newest `keep` history .md/.json pairs."""
        md_files = sorted(
            self.history_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in md_files[keep:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)

    def _prune_run_logs(self, keep: int = HISTORY_KEEP) -> None:
        logs = sorted(
            self.logs_dir.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in logs[keep:]:
            old.unlink(missing_ok=True)

    def write_last10_index(self) -> Path:
        """Write reports/last-10.md — compact index of recent runs for agents."""
        md_files = sorted(
            self.history_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:HISTORY_KEEP]

        lines = [
            f"# Last {HISTORY_KEEP} runs",
            "",
            "Cloud Agent: read this file + `reports/last-run.md` before diagnosing.",
            f"Full reports: `reports/history/<run_id>.md` (kept ≤{HISTORY_KEEP}).",
            "",
            "| # | run_id | status | processed | trigger | error |",
            "|---|--------|--------|-----------|---------|-------|",
        ]
        details: list[str] = []
        for idx, path in enumerate(md_files, start=1):
            data = self._load_history_json(path)
            run_id = data.get("run_id") or path.stem
            status = data.get("status") or "?"
            processed = data.get("processed", "—")
            trigger = (data.get("trigger_id") or "—")[:40]
            errors = data.get("errors") or []
            err = _redact(str(errors[0])[:120]) if errors else "—"
            err_cell = err.replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {idx} | `{run_id}` | **{status}** | {processed} | `{trigger}` | {err_cell} |"
            )
            details.append(self._history_detail_block(idx, path, data))

        lines.extend(["", "## Details", ""])
        if details:
            lines.extend(details)
        else:
            lines.append("(no history yet)")
        lines.append("")

        index_path = self.reports_dir / "last-10.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")
        agent_path = self.reports_dir / "AGENT.md"
        agent_path.write_text(
            "\n".join(
                [
                    "# Agent lookup — Kontent Zavod runs",
                    "",
                    "Always inspect these before guessing:",
                    "",
                    "1. `reports/last-run.md` — newest full report + log tail",
                    "2. `reports/last-10.md` — index of the last 10 iterations",
                    "3. `reports/history/<run_id>.md` — full report for a past run",
                    "4. `reports/diagnose.md` — VPS health (if present)",
                    "",
                    "On GitHub (after VPS publish):",
                    "",
                    "```bash",
                    "git fetch origin run-reports",
                    "git show origin/run-reports:reports/last-10.md",
                    "git show origin/run-reports:reports/last-run.md",
                    "```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return index_path

    @staticmethod
    def _load_history_json(md_path: Path) -> dict[str, Any]:
        json_path = md_path.with_suffix(".json")
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"run_id": md_path.stem}

    @staticmethod
    def _history_detail_block(idx: int, path: Path, data: dict[str, Any]) -> str:
        run_id = data.get("run_id") or path.stem
        status = data.get("status") or "?"
        started = data.get("started_at") or "—"
        finished = data.get("finished_at") or "—"
        errors = data.get("errors") or []
        stages = data.get("stages") or []
        tail = data.get("log_tail") or ""
        stage_line = ", ".join(
            f"{s.get('name')}" for s in stages[-8:]
        ) or "(none)"
        err_block = _redact("\n".join(str(e) for e in errors[:3])) if errors else "(none)"
        if len(tail) > 2500:
            tail = "…\n" + tail[-2500:]
        return "\n".join(
            [
                f"### {idx}. `{run_id}` — **{status}**",
                f"- file: `reports/history/{path.name}`",
                f"- started: {started} → finished: {finished}",
                f"- stages: {stage_line}",
                "- errors:",
                "```",
                err_block,
                "```",
                "- log_tail:",
                "```",
                _redact(tail) if tail else "(empty)",
                "```",
                "",
            ]
        )

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
