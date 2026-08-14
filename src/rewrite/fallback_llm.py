"""Fallback LLM rewrite via OpenAI-compatible API (OpenRouter / OpenAI)."""

from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from src.config import Settings
from src.models import RemakeSpec, SourceMeta, TranscriptResult

logger = logging.getLogger(__name__)

REMAKE_SCHEMA = """
{
  "hook": "string — 1-2 sec hook",
  "script": "string — full voiceover 20-40 sec, conversational RU",
  "shots": [{"keywords": ["stock", "search", "terms"], "duration_sec": 3.0}],
  "caption": "string — Instagram caption",
  "hashtags": ["#tag1", "#tag2"],
  "title": "string — short title"
}
"""


class FallbackRewriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = self._build_client(settings)

    def _build_client(self, settings: Settings) -> OpenAI | None:
        if not settings.llm_api_key:
            return None

        kwargs: dict = {"api_key": settings.llm_api_key}
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
            kwargs["default_headers"] = {
                "HTTP-Referer": "https://github.com/kontent-zavod",
                "X-Title": "Kontent Zavod",
            }
        return OpenAI(**kwargs)

    def rewrite(
        self,
        brand_prompt: str,
        meta: SourceMeta,
        transcript: TranscriptResult,
    ) -> RemakeSpec:
        if not self.client:
            raise RuntimeError(
                "OPENROUTER_API_KEY or OPENAI_API_KEY not set — cannot use fallback rewriter"
            )

        user_prompt = f"""
Прочитай бренд-бриф и исходный ролик. Создай ОРИГИНАЛЬНЫЙ сценарий для faceless Reels.
Не копируй чужие фразы — возьми только тему, хук и структуру.

## Бренд-бриф
{brand_prompt}

## Исходник
- Название: {meta.title}
- Канал: {meta.channel}
- Просмотры: {meta.views}
- URL: {meta.url}

## Транскрипт исходника
{transcript.text or "(пусто — придумай по названию)"}

Верни ТОЛЬКО валидный JSON без markdown по схеме:
{REMAKE_SCHEMA}
"""
        logger.info("Fallback rewrite via %s model=%s", self.settings.llm_base_url or "openai", self.settings.llm_model)
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты сценарист коротких Reels на русском. Отвечай только JSON.",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        raw = response.choices[0].message.content or ""
        return _parse_remake(raw)


def _parse_remake(raw: str) -> RemakeSpec:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return RemakeSpec.model_validate(data)
