"""Render a job from existing remake.json and optionally publish to Telegram."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import ensure_dirs, load_settings
from src.jobs import job_dir, read_remake, write_caption
from src.models import RemakeSpec, today_output_dir
from src.pipeline import _slugify
from src.publish.telegram import notify_owner
from src.renderers.factory import get_renderer
from src.visuals.pexels import PexelsClient
from src.voice.elevenlabs import ElevenLabsVoice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("render_job")


def render_job(
    job_id: str,
    *,
    output_suffix: str = "",
    renderer: str = "",
    refresh_shots: bool = False,
    publish: bool = False,
    post_text: str | None = None,
) -> Path:
    load_dotenv()
    if renderer:
        os.environ["RENDERER"] = renderer
    settings = load_settings()
    ensure_dirs(settings)
    path = job_dir(settings.jobs_dir, job_id)
    remake = read_remake(path)

    voice = ElevenLabsVoice(settings)
    voice_result = voice.synthesize(path, remake)
    logger.info("Voice: %.1fs", voice_result.duration_sec)

    renderer = get_renderer(settings)
    shots: list[Path] = []
    renderer_mode = settings.renderer.lower()
    if renderer_mode in ("faceless", "hybrid"):
        shots = PexelsClient(settings).download_shots(
            path, remake, refresh=refresh_shots
        )
    final = renderer.render(path, remake, voice_result, shots)

    out_dir = Path(today_output_dir(str(settings.output_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(remake.title or job_id)
    if output_suffix:
        slug = f"{slug}_{output_suffix}"
    dest = out_dir / f"{slug}.mp4"
    shutil.copy2(final, dest)
    write_caption(out_dir, slug, remake.caption, remake.hashtags)
    logger.info("Output: %s", dest)

    if publish:
        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
        text = post_text or f"{remake.caption}\n\n{' '.join(remake.hashtags)}"
        notify_owner(token, chat_id, dest, text)
        logger.info("Sent to Telegram DM")

    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Render job from remake.json")
    parser.add_argument("job_id", help="Job folder name under jobs/")
    parser.add_argument("--suffix", default="", help="Output filename suffix")
    parser.add_argument(
        "--renderer",
        choices=("faceless", "heygen", "hybrid"),
        default="",
        help="Override RENDERER from .env",
    )
    parser.add_argument(
        "--refresh-shots",
        action="store_true",
        help="Re-download Pexels clips (ignore cache)",
    )
    parser.add_argument("--publish", action="store_true", help="Send to your Telegram DM")
    parser.add_argument("--post-text", default="", help="Telegram caption override")
    args = parser.parse_args()

    try:
        render_job(
            args.job_id,
            output_suffix=args.suffix,
            renderer=args.renderer,
            refresh_shots=args.refresh_shots,
            publish=args.publish,
            post_text=args.post_text or None,
        )
    except Exception as exc:
        logger.exception("Failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
