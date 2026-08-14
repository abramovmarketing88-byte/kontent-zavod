"""Job directory helpers."""

from __future__ import annotations

import json
from pathlib import Path

from src.models import RemakeSpec, SourceMeta, TranscriptResult


def job_dir(jobs_root: Path, source_id: str) -> Path:
    path = jobs_root / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_source(job_path: Path, meta: SourceMeta) -> None:
    (job_path / "source.json").write_text(
        meta.model_dump_json(indent=2),
        encoding="utf-8",
    )


def read_source(job_path: Path) -> SourceMeta:
    return SourceMeta.model_validate_json(
        (job_path / "source.json").read_text(encoding="utf-8")
    )


def write_transcript(job_path: Path, transcript: TranscriptResult) -> None:
    (job_path / "transcript.json").write_text(
        transcript.model_dump_json(indent=2),
        encoding="utf-8",
    )


def read_transcript(job_path: Path) -> TranscriptResult:
    return TranscriptResult.model_validate_json(
        (job_path / "transcript.json").read_text(encoding="utf-8")
    )


def write_remake(job_path: Path, remake: RemakeSpec) -> None:
    (job_path / "remake.json").write_text(
        remake.model_dump_json(indent=2),
        encoding="utf-8",
    )


def read_remake(job_path: Path) -> RemakeSpec:
    return RemakeSpec.model_validate_json(
        (job_path / "remake.json").read_text(encoding="utf-8")
    )


def write_caption(output_dir: Path, slug: str, caption: str, hashtags: list[str]) -> None:
    tags = " ".join(hashtags)
    text = f"{caption}\n\n{tags}".strip()
    (output_dir / f"{slug}_caption.txt").write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
