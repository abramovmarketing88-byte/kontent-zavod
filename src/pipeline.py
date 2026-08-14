"""Main pipeline orchestrator."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import Settings, ensure_dirs, load_settings
from src.util import slugify
from src.db import Database
from src.discover.service import discover_sources
from src.jobs import (
    job_dir,
    write_caption,
    write_remake,
    write_source,
    write_transcript,
)
from src.models import JobStatus, today_output_dir
from src.publish.telegram import notify_owner
from src.renderers.factory import get_renderer
from src.rewrite.cursor_rewriter import CursorRewriter
from src.visuals.pexels import PexelsClient
from src.voice.elevenlabs import ElevenLabsVoice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self._analyzer = None
        self.rewriter = CursorRewriter(settings)
        self.voice = ElevenLabsVoice(settings)
        self.pexels = PexelsClient(settings)
        self.renderer = get_renderer(settings)

    @property
    def analyzer(self):
        if self._analyzer is None:
            from src.analyze.transcript import Analyzer

            self._analyzer = Analyzer(self.settings)
        return self._analyzer

    def run_once(self) -> int:
        sources = discover_sources(self.settings, self.db)
        if not sources:
            logger.info("No new sources to process")
            return 0

        processed = 0
        for meta in sources[: self.settings.max_videos_per_run]:
            try:
                self._process_one(meta)
                processed += 1
            except Exception as exc:
                logger.exception("Failed to process %s: %s", meta.source_id, exc)
                self.db.update_status(meta.source_id, JobStatus.FAILED, str(exc))
        return processed

    def _process_one(self, meta) -> None:
        path = job_dir(self.settings.jobs_dir, meta.source_id)
        self.db.upsert_source(meta, str(path), JobStatus.DISCOVERED)
        write_source(path, meta)
        logger.info("=== Processing %s: %s ===", meta.source_id, meta.title)

        transcript = self.analyzer.analyze(path, meta)
        write_transcript(path, transcript)
        self.db.update_status(meta.source_id, JobStatus.ANALYZED)

        remake = self.rewriter.rewrite(path, meta, transcript)
        write_remake(path, remake)
        self.db.update_status(meta.source_id, JobStatus.REWRITTEN)

        voice_result = self.voice.synthesize(path, remake)
        self.db.update_status(meta.source_id, JobStatus.VOICED)

        shot_clips: list[Path] = []
        if self.settings.renderer.lower() in ("faceless", "hybrid"):
            shot_clips = self.pexels.download_shots(path, remake)

        final = self.renderer.render(path, remake, voice_result, shot_clips)
        self.db.update_status(meta.source_id, JobStatus.RENDERED)

        out_dir = Path(today_output_dir(str(self.settings.output_dir)))
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(remake.title or meta.source_id)
        dest_video = out_dir / f"{slug}.mp4"
        shutil.copy2(final, dest_video)
        write_caption(out_dir, slug, remake.caption, remake.hashtags)
        logger.info("Output: %s", dest_video)

        if self.settings.telegram_notify:
            caption = (
                f"🎬 Готов новый Reels\n\n{remake.caption}\n\n"
                f"{' '.join(remake.hashtags)}"
            )
            notify_owner(
                self.settings.telegram_bot_token,
                self.settings.telegram_owner_chat_id,
                dest_video,
                caption,
            )
            self.db.update_status(meta.source_id, JobStatus.PUBLISHED)
            logger.info("Sent to Telegram DM: %s", self.settings.telegram_owner_chat_id)


def _parse_daily_at(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid DAILY_AT={value!r}, expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid DAILY_AT={value!r}")
    return hour, minute


def _start_scheduler(settings: Settings, pipeline: Pipeline) -> None:
    scheduler = BlockingScheduler(timezone=ZoneInfo(settings.schedule_tz))

    if settings.daily_at:
        hour, minute = _parse_daily_at(settings.daily_at)
        trigger = CronTrigger(hour=hour, minute=minute)
        logger.info(
            "Daily schedule: %02d:%02d %s, max %d video(s)/run",
            hour,
            minute,
            settings.schedule_tz,
            settings.max_videos_per_run,
        )
    else:
        trigger = IntervalTrigger(hours=settings.schedule_hours)
        logger.info(
            "Interval schedule: every %d hour(s), max %d video(s)/run",
            settings.schedule_hours,
            settings.max_videos_per_run,
        )

    scheduler.add_job(pipeline.run_once, trigger)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kontent Zavod — faceless Reels factory")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit",
    )
    args = parser.parse_args()

    settings = load_settings()
    ensure_dirs(settings)
    pipeline = Pipeline(settings)

    if args.once:
        count = pipeline.run_once()
        logger.info("Done. Processed %d video(s).", count)
        sys.exit(0)

    _start_scheduler(settings, pipeline)


if __name__ == "__main__":
    main()
