"""Rewrite source content via Cursor SDK."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.config import Settings
from src.models import RemakeSpec, SourceMeta, TranscriptResult
from src.rewrite.fallback_llm import FallbackRewriter, _parse_remake

logger = logging.getLogger(__name__)

BROLL_RULES = """
## B-roll (shots.keywords) — для Pexels
- Ключевые слова на АНГЛИЙСКОМ (Pexels ищет по EN).
- Динамика: fast motion, handheld, timelapse, action, walking, typing, city rush.
- Люди/офис: european, slavic, russian, eastern europe, moscow — визуал близкий к RU аудитории.
- НЕ добавляй african/black/afro/caribbean в keywords, если тема явно не про это.
- 4–6 шотов, 2–4 сек каждый, смена планов (крупный → общий → действие).
"""


{
  "hook": "string",
  "script": "string",
  "shots": [{"keywords": ["..."], "duration_sec": 3.0}],
  "caption": "string",
  "hashtags": ["#..."],
  "title": "string"
}
"""


class CursorRewriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fallback = FallbackRewriter(settings)

    def rewrite(
        self,
        job_path: Path,
        meta: SourceMeta,
        transcript: TranscriptResult,
        duration_hint: str | None = None,
        research_context: str | None = None,
    ) -> RemakeSpec:
        remake_path = job_path / "remake.json"
        brand_prompt = (self.settings.brand_dir / "prompt.md").read_text(
            encoding="utf-8"
        )

        prompt = self._build_prompt(
            brand_prompt, meta, transcript, remake_path, duration_hint, research_context
        )

        try:
            remake = self._cursor_prompt(prompt, remake_path)
            logger.info("Cursor rewrite OK for %s", meta.source_id)
            return remake
        except Exception as exc:
            logger.warning(
                "Cursor rewrite failed for %s: %s — trying fallback",
                meta.source_id,
                exc,
            )
            remake = self.fallback.rewrite(
                brand_prompt,
                meta,
                transcript,
                duration_hint=duration_hint,
                research_context=research_context,
            )
            remake_path.write_text(remake.model_dump_json(indent=2), encoding="utf-8")
            return remake

    def _build_prompt(
        self,
        brand_prompt: str,
        meta: SourceMeta,
        transcript: TranscriptResult,
        remake_path: Path,
        duration_hint: str | None = None,
        research_context: str | None = None,
    ) -> str:
        source_json = json.dumps(
            {
                "title": meta.title,
                "views": meta.views,
                "channel": meta.channel,
                "url": meta.url,
                "platform": meta.platform,
                "transcript": transcript.text,
            },
            ensure_ascii=False,
            indent=2,
        )
        research_block = ""
        if research_context:
            research_block = f"""
## Ресёрч из интернета (используй факты и углы — не выдумывай)
{research_context}
"""
        if meta.platform == "topic":
            return f"""
Прочитай brand/prompt.md, РЕСЁРЧ и ТЕМУ ниже.
Создай ОРИГИНАЛЬНЫЙ вирусный сценарий faceless Reels на русском с нуля (не ремейк).
Опирайся на ресёрч: факты, тренды, боль аудитории. Хук — максимально цепкий.
Если в теме есть блок «ИСПОЛЬЗУЙ ЭТОТ ТЕКСТ ОЗВУЧКИ» — возьми script почти дословно, не переписывай смысл.
Длина озвучки: строго 30–40 секунд (~75–100 слов).

Запиши результат в файл: {remake_path.as_posix()}

Формат JSON (строго):
{REMAKE_SCHEMA}
{BROLL_RULES}

## brand/prompt.md
{brand_prompt}
{research_block}
## Тема / ТЗ
{source_json}
{f"## Дополнительное требование\n{duration_hint}\n" if duration_hint else ""}
Важно: файл remake.json должен быть валидным JSON без комментариев.
"""
        return f"""
Прочитай brand/prompt.md и данные исходника ниже.
Создай ОРИГИНАЛЬНЫЙ сценарий faceless Reels на русском (бизнес/маркетинг).
Не копируй чужой текст дословно — только тему, хук и структуру.
Длина озвучки: строго 30–40 секунд (~75–100 слов).

Запиши результат в файл: {remake_path.as_posix()}

Формат JSON (строго):
{REMAKE_SCHEMA}
{BROLL_RULES}

## brand/prompt.md
{brand_prompt}

## source.json
{source_json}
{f"## Дополнительное требование\n{duration_hint}\n" if duration_hint else ""}
Важно: файл remake.json должен быть валидным JSON без комментариев.
"""

    def _cursor_prompt(self, prompt: str, remake_path: Path) -> RemakeSpec:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

        if not self.settings.cursor_api_key:
            raise RuntimeError("CURSOR_API_KEY not set")

        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=self.settings.cursor_api_key,
                model="composer-2.5",
                local=LocalAgentOptions(cwd=str(self.settings.root)),
            ),
        )

        if result.status == "error":
            raise RuntimeError(f"Cursor agent run failed: {result.id}")

        if remake_path.exists():
            return RemakeSpec.model_validate_json(
                remake_path.read_text(encoding="utf-8")
            )

        # Agent may return JSON in text instead of writing file
        if result.result:
            return _parse_remake(result.result)

        raise FileNotFoundError(f"remake.json not created at {remake_path}")
