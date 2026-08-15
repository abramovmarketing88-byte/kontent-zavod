"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class NicheConfig:
    search_queries: list[str] = field(default_factory=list)
    min_views: int = 50_000
    max_age_days: int = 14
    top_n_per_query: int = 5
    max_duration_sec: int = 60
    title_stopwords: list[str] = field(default_factory=list)


@dataclass
class InstagramNicheConfig:
    hashtags: list[str] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)
    min_views: int = 50_000
    max_age_days: int = 14
    max_duration_sec: int = 60


@dataclass
class Settings:
    root: Path
    data_dir: Path
    jobs_dir: Path
    output_dir: Path
    inbox_dir: Path
    brand_dir: Path
    config_dir: Path
    db_path: Path

    cursor_api_key: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    youtube_api_key: str
    pexels_api_key: str
    llm_api_key: str
    llm_base_url: str | None
    llm_model: str

    heygen_api_key: str
    heygen_avatar_id: str
    heygen_intro_sec: float
    renderer: str

    telegram_bot_token: str
    telegram_owner_chat_id: str
    telegram_notify: bool

    max_videos_per_run: int
    schedule_hours: int
    daily_at: str
    schedule_tz: str
    whisper_model: str
    transcribe_backend: str
    target_duration_min: float
    target_duration_max: float

    niche: NicheConfig
    instagram: InstagramNicheConfig

    # Optional YouTube Shorts upload (OAuth — not the Data API key)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_upload: bool = False
    youtube_privacy: str = "public"
    youtube_category_id: str = "22"


def _load_llm_settings() -> tuple[str, str | None, str]:
    """Resolve fallback LLM: OpenRouter or OpenAI-compatible API."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    llm_api_key = openrouter_key or openai_key

    llm_base_url = os.getenv("LLM_BASE_URL") or None
    if not llm_base_url and (openrouter_key or llm_api_key.startswith("sk-or-v1-")):
        llm_base_url = "https://openrouter.ai/api/v1"

    llm_model = (
        os.getenv("LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or ("openai/gpt-4o-mini" if llm_base_url else "gpt-4o-mini")
    )
    return llm_api_key, llm_base_url, llm_model


def load_settings() -> Settings:
    load_dotenv()
    root = Path(os.getenv("PROJECT_ROOT", ".")).resolve()

    niche_path = root / "config" / "niche.yaml"
    niche_data = yaml.safe_load(niche_path.read_text(encoding="utf-8")) or {}
    niche = NicheConfig(
        search_queries=niche_data.get("search_queries", []),
        min_views=int(niche_data.get("min_views", 50_000)),
        max_age_days=int(niche_data.get("max_age_days", 14)),
        top_n_per_query=int(niche_data.get("top_n_per_query", 5)),
        max_duration_sec=int(niche_data.get("max_duration_sec", 60)),
        title_stopwords=list(niche_data.get("title_stopwords") or []),
    )

    ig_data = niche_data.get("instagram") or {}
    instagram = InstagramNicheConfig(
        hashtags=ig_data.get("hashtags", []),
        accounts=ig_data.get("accounts", []),
        min_views=int(ig_data.get("min_views", niche.min_views)),
        max_age_days=int(ig_data.get("max_age_days", niche.max_age_days)),
        max_duration_sec=int(ig_data.get("max_duration_sec", niche.max_duration_sec)),
    )

    llm_api_key, llm_base_url, llm_model = _load_llm_settings()

    return Settings(
        root=root,
        data_dir=root / "data",
        jobs_dir=root / "jobs",
        output_dir=root / "output",
        inbox_dir=root / "inbox",
        brand_dir=root / "brand",
        config_dir=root / "config",
        db_path=root / "data" / "factory.db",
        cursor_api_key=os.getenv("CURSOR_API_KEY", ""),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
        youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID", ""),
        youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        youtube_refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", ""),
        youtube_upload=os.getenv("YOUTUBE_UPLOAD", "false").lower()
        in ("1", "true", "yes"),
        youtube_privacy=os.getenv("YOUTUBE_PRIVACY", "public"),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "22"),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        heygen_api_key=os.getenv("HEYGEN_API_KEY", ""),
        heygen_avatar_id=os.getenv("HEYGEN_AVATAR_ID", ""),
        heygen_intro_sec=float(os.getenv("HEYGEN_INTRO_SEC", "8")),
        renderer=os.getenv("RENDERER", "faceless"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_owner_chat_id=os.getenv("TELEGRAM_OWNER_CHAT_ID", ""),
        telegram_notify=os.getenv("TELEGRAM_NOTIFY", "false").lower()
        in ("1", "true", "yes"),
        max_videos_per_run=int(os.getenv("MAX_VIDEOS_PER_RUN", "1")),
        schedule_hours=int(os.getenv("SCHEDULE_HOURS", "6")),
        daily_at=os.getenv("DAILY_AT", "09:00"),
        schedule_tz=os.getenv("SCHEDULE_TZ", "Europe/Moscow"),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        transcribe_backend=os.getenv("TRANSCRIBE_BACKEND", "faster_whisper"),
        target_duration_min=float(os.getenv("TARGET_DURATION_MIN", "30")),
        target_duration_max=float(os.getenv("TARGET_DURATION_MAX", "40")),
        niche=niche,
        instagram=instagram,
    )


def ensure_dirs(settings: Settings) -> None:
    for path in (
        settings.data_dir,
        settings.jobs_dir,
        settings.output_dir,
        settings.inbox_dir / "processed",
    ):
        path.mkdir(parents=True, exist_ok=True)
