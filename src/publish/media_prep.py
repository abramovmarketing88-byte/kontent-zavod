"""Caption / hashtag helpers for platform limits."""

from __future__ import annotations


def clip_text(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def normalize_hashtags(tags: list[str], *, limit: int = 20) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = raw.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def join_caption(caption: str, hashtags: list[str], *, max_len: int) -> str:
    tags = " ".join(normalize_hashtags(hashtags))
    body = caption.strip()
    if tags:
        body = f"{body}\n\n{tags}".strip() if body else tags
    return clip_text(body, max_len)
