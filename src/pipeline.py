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

from src.author_nudge import maybe_welcome, note_successful_run
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
from src.publish.telegram import (
    notify_owner,
    send_document,
    send_message,
    send_source_breakdown,
)
from src.renderers.factory import get_renderer
from src.rewrite.cursor_rewriter import CursorRewriter
from src.run_report import RunReport, install_redact_logging
from src.visuals.pexels import PexelsClient
from src.voice.elevenlabs import ElevenLabsVoice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
install_redact_logging()
logger = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, settings: Settings, report: RunReport | None = None) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.report = report
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

    def _tg(self, text: str) -> None:
        if not self.settings.telegram_notify:
            return
        try:
            send_message(
                self.settings.telegram_bot_token,
                self.settings.telegram_owner_chat_id,
                text,
            )
        except Exception as exc:
            logger.warning("Telegram notify failed: %s", exc)

    def _send_report_file(self, caption: str) -> None:
        if not self.settings.telegram_notify or self.report is None:
            return
        path = self.settings.root / "reports" / "last-run.md"
        if not path.exists():
            return
        try:
            send_document(
                self.settings.telegram_bot_token,
                self.settings.telegram_owner_chat_id,
                path,
                caption=caption[:1024],
            )
        except Exception as exc:
            logger.warning("Telegram report document failed: %s", exc)
            self._tg(self.report.telegram_summary())

    def run_once(self) -> int:
        report = self.report
        if report:
            report.stage("discover")
        sources = discover_sources(self.settings, self.db)
        if not sources:
            logger.info("No new sources to process")
            if report:
                report.stage("discover_empty")
                report.complete(0, empty=True)
                self._send_report_file("⚠️ Нет новых Reels — отчёт прогона")
            self._tg(
                "⚠️ Разовый заказ: новых залетевших Reels не нашёл "
                "(все уже в базе или ниже порога просмотров).\n"
                "Кинь ссылку в inbox/urls.txt или подними min_views / дождись свежих."
            )
            return 0

        processed = 0
        last_error = ""
        # Try several discovered sources until we successfully finish max_videos_per_run
        for meta in sources:
            if processed >= self.settings.max_videos_per_run:
                break
            if report:
                report.add_source(meta)
            try:
                self._process_one(meta)
                processed += 1
            except Exception as exc:
                last_error = str(exc)
                logger.exception("Failed to process %s: %s", meta.source_id, exc)
                self.db.update_status(meta.source_id, JobStatus.FAILED, str(exc))
                if report:
                    report.stage("failed", f"{meta.source_id}: {exc}")
                    report.errors.append(f"{meta.source_id}: {exc}")
                self._tg(
                    f"❌ Не смог собрать ролик из «{meta.title}»\n"
                    f"{meta.url}\n\nОшибка: {exc}\nПробую следующий источник…"
                )
        if processed == 0 and last_error:
            if report:
                report.fail(RuntimeError(last_error))
                self._send_report_file("💥 Прогон упал — отчёт")
            raise RuntimeError(f"All videos failed; last error: {last_error}")
        if report:
            report.stage("done", f"processed={processed}")
            report.complete(processed)
            self._send_report_file(f"✅ Прогон ок — processed={processed}. last-run.md")
        if processed > 0:
            from src.author_nudge import note_successful_run

            note_successful_run(
                self.settings.data_dir,
                send_telegram=self._tg if self.settings.telegram_notify else None,
            )
        return processed

    def _process_one(self, meta) -> None:
        path = job_dir(self.settings.jobs_dir, meta.source_id)
        self.db.upsert_source(meta, str(path), JobStatus.DISCOVERED)
        write_source(path, meta)
        logger.info("=== Processing %s: %s ===", meta.source_id, meta.title)
        report = self.report
        if report:
            report.stage("analyze", meta.source_id)

        if meta.platform == "topic":
            # Freeform idea — no download / whisper
            from src.discover.topic import topic_brief_path
            from src.models import TranscriptResult

            brief_path = topic_brief_path(self.settings.inbox_dir, meta.source_id)
            topic_text = (
                brief_path.read_text(encoding="utf-8").strip()
                if brief_path.exists()
                else meta.title
            )
            (path / "topic.txt").write_text(topic_text + "\n", encoding="utf-8")
            transcript = TranscriptResult(text=topic_text, language="ru")
            write_transcript(path, transcript)
            self.db.update_status(meta.source_id, JobStatus.ANALYZED)
            if self.settings.telegram_notify:
                # topic_text already starts with the title line — don't repeat it
                self._tg(f"🧠 Тема без исходника\n\n{topic_text[:1800]}")
        else:
            transcript = self.analyzer.analyze(path, meta)
            write_transcript(path, transcript)
            self.db.update_status(meta.source_id, JobStatus.ANALYZED)

            if self.settings.telegram_notify:
                if report:
                    report.stage("breakdown", meta.source_id)
                structure = self.rewriter.fallback.analyze_structure(meta, transcript)
                send_source_breakdown(
                    self.settings.telegram_bot_token,
                    self.settings.telegram_owner_chat_id,
                    meta,
                    transcript,
                    structure,
                )

        if report:
            report.stage("rewrite", meta.source_id)
        remake = self.rewriter.rewrite(path, meta, transcript)
        write_remake(path, remake)
        self.db.update_status(meta.source_id, JobStatus.REWRITTEN)

        if report:
            report.stage("voice", meta.source_id)
        voice_result = self.voice.synthesize(path, remake)
        voice_result = self._ensure_target_duration(
            path, meta, transcript, remake, voice_result
        )
        self.db.update_status(meta.source_id, JobStatus.VOICED)

        shot_clips: list[Path] = []
        if self.settings.renderer.lower() in ("faceless", "hybrid"):
            if report:
                report.stage("pexels", meta.source_id)
            shot_clips = self.pexels.download_shots(path, remake)

        if report:
            report.stage("render", f"{self.settings.renderer}:{meta.source_id}")
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
            if report:
                report.stage("telegram_publish", str(dest_video))
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

        if self.settings.youtube_upload:
            self._publish_youtube(dest_video, remake, report)

        if self.settings.telegram_story_upload:
            self._publish_telegram_story(dest_video, remake, report)

    def _publish_telegram_story(self, dest_video, remake, report) -> None:
        from src.publish.telegram_story import (
            TelegramStoryError,
            discover_business_connection_id,
            prepare_story_video,
            post_story_video,
        )

        if report:
            report.stage("telegram_story", str(dest_video))
        try:
            conn = self.settings.telegram_business_connection_id.strip()
            if not conn:
                conn = discover_business_connection_id(self.settings.telegram_bot_token) or ""
            if not conn:
                cache = self.settings.data_dir / "business_connection.id"
                if cache.exists():
                    conn = cache.read_text(encoding="utf-8").strip()
            prepared = self.settings.data_dir / f"story_{dest_video.stem}.mp4"
            prepare_story_video(dest_video, prepared)
            story = post_story_video(
                self.settings.telegram_bot_token,
                conn,
                prepared,
                caption=(remake.caption or remake.title or "")[:500],
                active_period=self.settings.telegram_story_active_period,
            )
            self._tg(
                f"✅ Telegram Story\nstory_id={story.get('id')}\n"
                f"chat={(story.get('chat') or {}).get('id')}"
            )
        except TelegramStoryError as exc:
            logger.exception("Telegram story failed: %s", exc)
            if report:
                report.errors.append(f"telegram_story: {exc}")
            self._tg(f"❌ Telegram Story failed\n{exc}")

    def _publish_youtube(self, dest_video, remake, report) -> None:
        from src.publish.youtube import YouTubeUploadError, YouTubeUploader

        if report:
            report.stage("youtube_publish", str(dest_video))
        try:
            uploader = YouTubeUploader(
                client_id=self.settings.youtube_client_id,
                client_secret=self.settings.youtube_client_secret,
                refresh_token=self.settings.youtube_refresh_token,
                privacy=self.settings.youtube_privacy,
                category_id=self.settings.youtube_category_id,
            )
            tags = [h.lstrip("#") for h in (remake.hashtags or []) if h]
            result = uploader.upload_short(
                dest_video,
                title=remake.title or remake.hook or dest_video.stem,
                description=(
                    f"{remake.caption}\n\n" + " ".join(remake.hashtags or [])
                ).strip(),
                tags=tags,
            )
            self._tg(f"✅ YouTube Short\n{result['title']}\n{result['url']}")
            logger.info("YouTube Short: %s", result["url"])
        except YouTubeUploadError as exc:
            logger.exception("YouTube upload failed: %s", exc)
            if report:
                report.errors.append(f"youtube_upload: {exc}")
            self._tg(f"❌ YouTube Short upload failed\n{exc}")

    def _ensure_target_duration(self, path, meta, transcript, remake, voice_result):
        min_sec = self.settings.target_duration_min
        max_sec = self.settings.target_duration_max
        duration = voice_result.duration_sec

        if min_sec <= duration <= max_sec:
            return voice_result

        if duration < min_sec:
            hint = (
                f"Озвучка получилась {duration:.1f} сек — слишком коротко. "
                f"Перепиши script так, чтобы итоговая озвучка была {min_sec:.0f}–{max_sec:.0f} сек "
                f"(~75–100 слов). Добавь конкретики и один пример."
            )
        else:
            hint = (
                f"Озвучка получилась {duration:.1f} сек — слишком длинно. "
                f"Сократи script до {min_sec:.0f}–{max_sec:.0f} сек (~75–100 слов), "
                f"убери воду, оставь хук, проблему, решение и CTA."
            )

        logger.warning(
            "Voice duration %.1fs outside %.0f–%.0fs — retry rewrite",
            duration,
            min_sec,
            max_sec,
        )
        remake = self.rewriter.rewrite(path, meta, transcript, duration_hint=hint)
        write_remake(path, remake)
        self.db.update_status(meta.source_id, JobStatus.REWRITTEN)
        return self.voice.synthesize(path, remake)


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


def _notify_run_start(settings: Settings) -> None:
    if not settings.telegram_notify:
        logger.info("TELEGRAM_NOTIFY is off — skip start ping")
        return
    send_message(
        settings.telegram_bot_token,
        settings.telegram_owner_chat_id,
        "⏳ Разовый заказ: ищу залетевшие Reels, делаю разбор и собираю новый ролик. Пришлю сюда.",
    )
    logger.info("Sent run-once start ping to Telegram")


def _notify_run_crash(
    settings: Settings,
    exc: BaseException,
    report: RunReport | None = None,
) -> None:
    if report is not None:
        try:
            report.fail(exc)
        except Exception as write_exc:
            logger.warning("Failed to write crash report: %s", write_exc)
    if not settings.telegram_notify:
        return
    try:
        text = (
            report.telegram_summary()
            if report is not None
            else f"💥 Разовый заказ упал: {exc}"
        )
        send_message(
            settings.telegram_bot_token,
            settings.telegram_owner_chat_id,
            text,
        )
        report_path = settings.root / "reports" / "last-run.md"
        if report_path.exists():
            send_document(
                settings.telegram_bot_token,
                settings.telegram_owner_chat_id,
                report_path,
                caption="💥 last-run.md — отдай агенту / приложи к Issue",
            )
    except Exception as notify_exc:
        logger.warning("Failed to send crash notify: %s", notify_exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kontent Zavod — faceless Reels factory")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit",
    )
    parser.add_argument(
        "--notify-start",
        action="store_true",
        help="Ping Telegram before a one-off run",
    )
    args = parser.parse_args()

    settings = load_settings()
    ensure_dirs(settings)
    report = RunReport(settings) if args.once else None
    pipeline = Pipeline(settings, report=report)

    def _nudge_tg(text: str) -> None:
        if settings.telegram_notify and settings.telegram_bot_token and settings.telegram_owner_chat_id:
            send_message(
                settings.telegram_bot_token,
                settings.telegram_owner_chat_id,
                text,
            )

    maybe_welcome(settings.data_dir, send_telegram=_nudge_tg if settings.telegram_notify else None)

    if args.notify_start:
        try:
            _notify_run_start(settings)
        except Exception as exc:
            logger.exception("Start notify failed: %s", exc)

    if args.once:
        try:
            count = pipeline.run_once()
        except Exception as exc:
            logger.exception("Pipeline --once failed: %s", exc)
            _notify_run_crash(settings, exc, report)
            sys.exit(1)
        logger.info("Done. Processed %d video(s).", count)
        sys.exit(0)

    _start_scheduler(settings, pipeline)


if __name__ == "__main__":
    main()
