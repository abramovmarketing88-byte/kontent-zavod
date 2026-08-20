"""B-roll query tuning — dynamic clips, Russian/European visual context."""

from __future__ import annotations

import re

from src.research.topic_research import topic_allows_global_cast

# Appended to people/office/lifestyle shots when global cast is not requested.
EUROPEAN_VISUAL_SUFFIX = (
    "european slavic russian eastern europe moscow office dynamic fast motion"
)

# Makes clips feel more energetic on Reels.
DYNAMIC_SUFFIX = "dynamic fast paced handheld timelapse cinematic vertical 4k"

# Avoid in Pexels queries unless topic explicitly needs global/diverse cast.
AVOID_CAST_TERMS = (
    "african",
    "african american",
    "black people",
    "afro",
    "caribbean",
    "jamaican",
)

PEOPLE_HINTS = (
    "person",
    "people",
    "man",
    "woman",
    "team",
    "office",
    "businessman",
    "businesswoman",
    "entrepreneur",
    "worker",
    "employee",
    "meeting",
    "face",
    "portrait",
    "couple",
    "family",
    "crowd",
    "рус",
    "офис",
    "человек",
    "люди",
    "бизнес",
    "предприним",
)


def _looks_like_people_shot(keywords: list[str]) -> bool:
    blob = " ".join(keywords).lower()
    return any(h in blob for h in PEOPLE_HINTS)


def enhance_broll_query(
    keywords: list[str],
    *,
    topic: str = "",
    shot_index: int = 0,
) -> str:
    """Build a Pexels search query with dynamic motion + regional visual bias."""
    base = " ".join(k.strip() for k in keywords if k.strip()).strip()
    if not base:
        base = "cinematic business vertical"

    parts = [base, DYNAMIC_SUFFIX]
    if _looks_like_people_shot(keywords) and not topic_allows_global_cast(topic):
        parts.append(EUROPEAN_VISUAL_SUFFIX)
        for term in AVOID_CAST_TERMS:
            base = re.sub(re.escape(term), "", base, flags=re.I)

    # Rotate emphasis so consecutive shots don't look identical.
    rotate = ("close up action", "wide shot movement", "over shoulder work", "street city")
    parts.append(rotate[shot_index % len(rotate)])

    query = " ".join(parts)
    query = " ".join(query.split())
    return query[:220]


def query_variants(primary: str, *, topic: str = "") -> list[str]:
    """Fallback queries if the primary search returns nothing."""
    variants = [primary]
    if not topic_allows_global_cast(topic):
        variants.append(
            primary
            + " european russian slavic business dynamic vertical"
        )
    variants.append("dynamic cinematic office europe vertical 4k fast")
    variants.append("timelapse city europe business vertical motion")
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out
