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
  "script": "string — full voiceover 30-40 sec (~75-100 words), conversational RU",
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
        duration_hint: str | None = None,
    ) -> RemakeSpec:
        if not self.client:
            raise RuntimeError(
                "OPENROUTER_API_KEY or OPENAI_API_KEY not set — cannot use fallback rewriter"
            )

        hint_block = f"\n\n## Дополнительное требование\n{duration_hint}\n" if duration_hint else ""

        user_prompt = f"""
Прочитай бренд-бриф и исходный ролик. Создай ОРИГИНАЛЬНЫЙ сценарий для faceless Reels.
Не копируй чужие фразы — возьми только тему, хук и структуру.
Длина озвучки: строго 30–40 секунд (~75–100 слов).

## Бренд-бриф
{brand_prompt}

## Исходник
- Название: {meta.title}
- Канал: {meta.channel}
- Просмотры: {meta.views}
- URL: {meta.url}

## Транскрипт исходника
{transcript.text or "(пусто — придумай по названию)"}
{hint_block}
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

    def analyze_structure(
        self,
        meta: SourceMeta,
        transcript: TranscriptResult,
    ) -> str:
        if not self.client or not transcript.text.strip():
            return ""

        prompt = f"""
Проанализируй залетевший короткий ролик. Верни 5–7 строк на русском:
- Хук (что цепляет в первые секунды)
- Проблема аудитории
- Решение / ценность
- CTA
- Почему мог залететь

Исходник: {meta.title} ({meta.channel})
Просмотры: {meta.views}
Транскрипт:
{transcript.text}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты аналитик вирального контента. Отвечай кратко списком.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("Structure analysis failed: %s", exc)
            return ""


def _parse_remake(raw: str) -> RemakeSpec:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return RemakeSpec.model_validate(data)
