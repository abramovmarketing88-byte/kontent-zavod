"""Gather web + YouTube signals for a topic before script writing."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from src.config import Settings
from src.models import SourceMeta

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"

# Topics where non-European / global cast in B-roll is expected.
GLOBAL_CAST_HINTS = (
    "африка",
    "africa",
    "афро",
    "afro",
    "hip hop",
    "hip-hop",
    "рэп",
    "rap",
    "nba",
    "nfl",
    "регби",
    "jazz",
    "джаз",
    "бразил",
    "brazil",
    "latin",
    "латино",
    "reggaeton",
    "кариб",
    "caribbean",
    "diversity",
    "инклюз",
    "black history",
    "история афр",
    "mlk",
    "колonial",
    "колони",
)


@dataclass
class ResearchResult:
    topic: str
    summary: str
    youtube_hits: list[str]
    web_snippets: list[str]
    viral_angles: list[str]

    def to_markdown(self) -> str:
        lines = [f"# Research: {self.topic}", "", "## Сводка", self.summary, ""]
        if self.viral_angles:
            lines.append("## Вирусные углы")
            lines.extend(f"- {a}" for a in self.viral_angles)
            lines.append("")
        if self.youtube_hits:
            lines.append("## YouTube / Shorts")
            lines.extend(f"- {h}" for h in self.youtube_hits[:8])
            lines.append("")
        if self.web_snippets:
            lines.append("## Интернет")
            lines.extend(f"- {s}" for s in self.web_snippets[:8])
        return "\n".join(lines).strip() + "\n"

    def prompt_block(self) -> str:
        parts = [self.summary.strip()]
        if self.viral_angles:
            parts.append("Вирусные углы:\n" + "\n".join(f"- {a}" for a in self.viral_angles))
        if self.youtube_hits:
            parts.append(
                "Что залетает на YouTube:\n"
                + "\n".join(f"- {h}" for h in self.youtube_hits[:6])
            )
        if self.web_snippets:
            parts.append(
                "Факты из интернета:\n"
                + "\n".join(f"- {s}" for s in self.web_snippets[:6])
            )
        return "\n\n".join(parts)


def topic_allows_global_cast(topic: str) -> bool:
    """True when topic explicitly calls for non-European / global visuals."""
    lowered = (topic or "").lower()
    return any(hint in lowered for hint in GLOBAL_CAST_HINTS)


class TopicResearcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def gather(
        self,
        job_path: Path,
        meta: SourceMeta,
        topic_text: str,
    ) -> ResearchResult:
        title = meta.title or topic_text.splitlines()[0]
        youtube_hits = self._search_youtube(title)
        web_snippets = self._search_web(title)
        raw_notes = {
            "topic": title,
            "youtube": youtube_hits,
            "web": web_snippets,
        }

        summary, angles = self._synthesize(title, raw_notes)
        result = ResearchResult(
            topic=title,
            summary=summary,
            youtube_hits=youtube_hits,
            web_snippets=web_snippets,
            viral_angles=angles,
        )

        research_path = job_path / "research.md"
        research_path.write_text(result.to_markdown(), encoding="utf-8")
        logger.info("Research saved: %s (%d yt, %d web)", research_path.name, len(youtube_hits), len(web_snippets))
        return result

    def _search_youtube(self, query: str) -> list[str]:
        key = self.settings.youtube_api_key
        if not key:
            return []
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoDuration": "short",
            "order": "viewCount",
            "maxResults": 8,
            "relevanceLanguage": "ru",
            "key": key,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(YOUTUBE_SEARCH, params=params)
                resp.raise_for_status()
                items = resp.json().get("items") or []
            hits: list[str] = []
            for item in items:
                sn = item.get("snippet") or {}
                title = (sn.get("title") or "").strip()
                channel = (sn.get("channelTitle") or "").strip()
                if title:
                    hits.append(f"{title} ({channel})" if channel else title)
            return hits
        except Exception as exc:
            logger.warning("YouTube topic research failed: %s", exc)
            return []

    def _search_web(self, query: str) -> list[str]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query + ' 2025 2026')}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; KontentZavod/1.0; +https://github.com/kontent-zavod)"
            ),
        }
        try:
            with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.warning("Web topic research failed: %s", exc)
            return []

        snippets: list[str] = []
        for match in re.finditer(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)>',
            html,
            flags=re.I | re.S,
        ):
            text = unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
            text = " ".join(text.split()).strip()
            if len(text) >= 40:
                snippets.append(text[:280])
            if len(snippets) >= 10:
                break
        return snippets

    def _synthesize(
        self,
        topic: str,
        raw_notes: dict,
    ) -> tuple[str, list[str]]:
        if not self.settings.llm_api_key:
            fallback = self._fallback_summary(topic, raw_notes)
            return fallback, []

        from openai import OpenAI

        kwargs: dict = {"api_key": self.settings.llm_api_key}
        if self.settings.llm_base_url:
            kwargs["base_url"] = self.settings.llm_base_url
            kwargs["default_headers"] = {
                "HTTP-Referer": "https://github.com/kontent-zavod",
                "X-Title": "Kontent Zavod",
            }
        client = OpenAI(**kwargs)

        yt = "\n".join(f"- {h}" for h in raw_notes.get("youtube") or []) or "(нет данных)"
        web = "\n".join(f"- {s}" for s in raw_notes.get("web") or []) or "(нет данных)"
        prompt = f"""
Тема Reels: {topic}

YouTube / Shorts по теме:
{yt}

Сниппеты из интернета:
{web}

Сделай краткий ресёрч для сценариста вирального Reels (30–40 сек, RU аудитория).
Верни JSON:
{{
  "summary": "5–8 предложений: факты, тренды, боль аудитории, что цепляет",
  "viral_angles": ["3–5 коротких вирусных угла / хуков"]
}}
Только JSON, без markdown.
"""
        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты аналитик вирального контента. Отвечай только JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
            )
            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            import json

            data = json.loads(raw)
            summary = str(data.get("summary") or "").strip()
            angles = [str(a).strip() for a in (data.get("viral_angles") or []) if str(a).strip()]
            if summary:
                return summary, angles
        except Exception as exc:
            logger.warning("Research LLM synthesis failed: %s", exc)

        return self._fallback_summary(topic, raw_notes), []

    @staticmethod
    def _fallback_summary(topic: str, raw_notes: dict) -> str:
        parts = [f"Тема: {topic}."]
        yt = raw_notes.get("youtube") or []
        web = raw_notes.get("web") or []
        if yt:
            parts.append("Популярные ролики: " + "; ".join(yt[:3]) + ".")
        if web:
            parts.append("Из интернета: " + " ".join(web[:2])[:400])
        if len(parts) == 1:
            parts.append("Сделай сильный хук и 2 конкретных примера по теме.")
        return " ".join(parts)
