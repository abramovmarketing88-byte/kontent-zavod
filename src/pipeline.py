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
    read_remake,
    read_transcript,
    write_caption,
    write_remake,
    write_source,
    write_transcript,
)
from src.models import JobStatus, OrderStatus, today_output_dir
from src.publish.telegram import (
    edit_message_text,
    send_document,
    send_message,
    send_source_breakdown,
)
from src.research.topic_research import TopicResearcher
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
        self.researcher = TopicResearcher(settings)
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

    def _order_card(
        self,
        order_id: str,
        status: OrderStatus,
        stage: str,
        text: str,
        *,
        reply_markup: dict | None = None,
        finished: bool = False,
        draft_version: int | None = None,
        error_code: str | None = None,
        error_user_text: str | None = None,
    ) -> None:
        order = self.db.update_order(
            order_id,
            status,
            current_stage=stage,
            draft_version=draft_version,
            error_code=error_code,
            error_user_text=error_user_text,
            finished=finished,
        )
        if not order or not self.settings.telegram_notify:
            return
        try:
            if order.status_message_id:
                edit_message_text(
                    self.settings.telegram_bot_token,
                    order.owner_chat_id,
                    order.status_message_id,
                    text[:4096],
                    reply_markup=reply_markup,
                )
            else:
                result = send_message(
                    self.settings.telegram_bot_token,
                    order.owner_chat_id,
                    text[:4096],
                    reply_markup=reply_markup,
                )
                self.db.set_status_message(
                    order_id, int(result["result"]["message_id"])
                )
        except Exception as exc:
            logger.warning("Order card update failed for %s: %s", order_id, exc)
            if order.status_message_id:
                try:
                    result = send_message(
                        self.settings.telegram_bot_token,
                        order.owner_chat_id,
                        text[:4096],
                        reply_markup=reply_markup,
                    )
                    self.db.set_status_message(
                        order_id, int(result["result"]["message_id"])
                    )
                except Exception as fallback_exc:
                    logger.warning(
                        "Order card fallback send failed for %s: %s",
                        order_id,
                        fallback_exc,
                    )

    def _order_cancelled(self, order_id: str) -> bool:
        order = self.db.get_order(order_id)
        return bool(order and order.status == OrderStatus.CANCELLED)

    def _publish_existing_order(self, order, meta, path: Path) -> bool:
        from src.publish.base import PublishMeta
        from src.publish.orchestrator import PublishOrchestrator, default_publishers

        video = Path(order.output_path)
        if not video.exists():
            raise FileNotFoundError(f"Rendered video missing for order {order.id}")
        remake = read_remake(path)
        self._order_card(
            order.id,
            OrderStatus.PUBLISHING,
            "publishing",
            f"📣 Заказ #{order.id}\nСтатус: публикую на подключённые площадки",
        )
        publishers = [p for p in default_publishers() if p.name != "telegram_dm"]
        results = PublishOrchestrator(
            self.settings,
            publishers=publishers,
            notify=self._tg if self.settings.telegram_notify else None,
            report=self.report,
        ).publish_all(
            video,
            PublishMeta(
                title=remake.title,
                caption=remake.caption,
                hashtags=list(remake.hashtags),
                source_id=meta.source_id,
                order_id=order.id,
                video_path=video,
            ),
        )
        if any(result.status == "ok" for result in results):
            self._order_card(
                order.id,
                OrderStatus.PUBLISHED,
                "published",
                f"✅ Заказ #{order.id}\nСтатус: опубликовано",
                finished=True,
            )
        else:
            self._order_card(
                order.id,
                OrderStatus.READY,
                "ready",
                f"⚠️ Заказ #{order.id}\nВидео готово, но публикация не выполнена.\n\n"
                "Проверь включённые PUBLISH_* и ключи площадок, затем нажми публикацию снова.",
                error_code="publish_not_completed",
                error_user_text="Ни одна подключённая площадка не подтвердила публикацию.",
            )
        return True

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
            return 0

        processed = 0
        deferred = 0
        last_error = ""
        # Try several discovered sources until we successfully finish max_videos_per_run
        for meta in sources:
            if processed >= self.settings.max_videos_per_run:
                break
            if report:
                report.add_source(meta)
            try:
                completed = self._process_one(meta)
                if completed:
                    processed += 1
                else:
                    deferred += 1
            except Exception as exc:
                last_error = str(exc)
                logger.exception("Failed to process %s: %s", meta.source_id, exc)
                self.db.update_status(meta.source_id, JobStatus.FAILED, str(exc))
                if meta.order_id:
                    from src.telegram.topic_intake import failed_keyboard

                    self._order_card(
                        meta.order_id,
                        OrderStatus.FAILED,
                        "failed",
                        f"❌ Заказ #{meta.order_id}\nСтатус: нужна помощь\n\n"
                        "Не удалось завершить текущий этап. Можно безопасно повторить заказ.",
                        reply_markup=failed_keyboard(meta.order_id),
                        finished=True,
                        error_code="pipeline_failed",
                        error_user_text="Не удалось завершить текущий этап.",
                    )
                if report:
                    report.stage("failed", f"{meta.source_id}: {exc}")
                    report.errors.append(f"{meta.source_id}: {exc}")
                if not meta.order_id:
                    self._tg(
                        f"❌ Не смог собрать ролик из «{meta.title}»\n"
                        f"{meta.url}\n\nОшибка: {exc}\nПробую следующий источник…"
                    )
        if self.db.has_runnable_orders():
            # Multiple Telegram messages may arrive before one trigger is consumed.
            # Wake the next run so every durable order eventually advances.
            from src.telegram.topic_intake import bump_run_once_trigger

            bump_run_once_trigger(self.settings.root)
        if processed == 0 and last_error:
            if report:
                report.fail(RuntimeError(last_error))
                self._send_report_file("💥 Прогон упал — отчёт")
            raise RuntimeError(f"All videos failed; last error: {last_error}")
        if report:
            report.stage("done", f"processed={processed} deferred={deferred}")
            report.complete(processed)
            self._send_report_file(f"✅ Прогон ок — processed={processed}. last-run.md")
        if processed > 0:
            from src.author_nudge import note_successful_run

            note_successful_run(
                self.settings.data_dir,
                send_telegram=self._tg if self.settings.telegram_notify else None,
            )
        return processed

    def _process_one(self, meta) -> bool:
        path = job_dir(self.settings.jobs_dir, meta.source_id)
        order = self.db.get_order(meta.order_id) if meta.order_id else None
        resume_stage = order.current_stage if order else ""
        if order and resume_stage == OrderStatus.PUBLISH_REQUESTED.value:
            return self._publish_existing_order(order, meta, path)
        renderer_mode = (
            order.renderer if order and order.renderer != "auto" else self.settings.renderer
        ).lower()
        renderer = get_renderer(self.settings, renderer_mode)
        self.db.upsert_source(meta, str(path), JobStatus.DISCOVERED)
        write_source(path, meta)
        logger.info("=== Processing %s: %s ===", meta.source_id, meta.title)
        report = self.report
        if report:
            report.stage("analyze", meta.source_id)

        research_context: str | None = None
        if order and resume_stage == OrderStatus.QUEUED.value:
            self._order_card(
                order.id,
                OrderStatus.PROCESSING,
                "research",
                f"🔎 Заказ #{order.id}\nСтатус: исследую тему и готовлю сценарий",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "🗑 Отменить", "callback_data": f"order:cancel:{order.id}"}
                    ]]
                },
            )
        if order and resume_stage == OrderStatus.APPROVED.value:
            transcript = read_transcript(path)
            remake = read_remake(path)
        elif order and resume_stage == OrderStatus.REVISION_REQUESTED.value:
            transcript = read_transcript(path)
            previous = read_remake(path)
            instruction = order.revision_instruction.strip()
            hint = (
                "Отредактируй предыдущий сценарий по инструкции пользователя.\n"
                f"ПРЕДЫДУЩИЙ СЦЕНАРИЙ:\n{previous.script}\n\n"
                f"ИНСТРУКЦИЯ ПОЛЬЗОВАТЕЛЯ:\n{instruction}"
            )
            remake = self.rewriter.rewrite(
                path,
                meta,
                transcript,
                duration_hint=hint,
            )
            write_remake(path, remake)
            self.db.update_status(meta.source_id, JobStatus.REWRITTEN)
            version = max(1, order.draft_version + 1)
            from src.telegram.topic_intake import draft_keyboard

            self._order_card(
                order.id,
                OrderStatus.DRAFT_READY,
                "draft_ready",
                f"📝 Заказ #{order.id} · сценарий v{version}\n\n"
                f"Хук: {remake.hook}\n\n{remake.script}\n\n"
                "Проверь текст. Озвучка и рендер ещё не запускались.",
                reply_markup=draft_keyboard(order.id),
                draft_version=version,
            )
            return False
        elif meta.platform == "topic":
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
            if self.settings.telegram_notify and not order:
                # topic_text already starts with the title line — don't repeat it
                self._tg(f"🧠 Тема без исходника\n\n{topic_text[:1800]}")

            if report:
                report.stage("research", meta.source_id)
            try:
                research = self.researcher.gather(path, meta, topic_text)
                research_context = research.prompt_block()
                if self.settings.telegram_notify and research.summary and not order:
                    preview = research.summary[:1200]
                    angles = ""
                    if research.viral_angles:
                        angles = "\n\nУглы:\n" + "\n".join(
                            f"• {a}" for a in research.viral_angles[:5]
                        )
                    self._tg(f"🔎 Ресёрч по теме\n\n{preview}{angles}")
            except Exception as exc:
                logger.warning("Topic research failed: %s", exc)
                if self.settings.telegram_notify and not order:
                    self._tg(f"⚠️ Ресёрч не удался ({exc}) — пишу сценарий по теме.")
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

        if order and self._order_cancelled(order.id):
            return False

        if not (order and resume_stage == OrderStatus.APPROVED.value):
            if order:
                self._order_card(
                    order.id,
                    OrderStatus.PROCESSING,
                    "rewrite",
                    f"✍️ Заказ #{order.id}\nСтатус: пишу сценарий",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "🗑 Отменить", "callback_data": f"order:cancel:{order.id}"}
                        ]]
                    },
                )
            if report:
                report.stage("rewrite", meta.source_id)
            remake = self.rewriter.rewrite(
                path, meta, transcript, research_context=research_context
            )
            write_remake(path, remake)
            self.db.update_status(meta.source_id, JobStatus.REWRITTEN)

        if order and resume_stage != OrderStatus.APPROVED.value:
            from src.telegram.topic_intake import draft_keyboard

            version = max(1, order.draft_version + 1)
            self._order_card(
                order.id,
                OrderStatus.DRAFT_READY,
                "draft_ready",
                f"📝 Заказ #{order.id} · сценарий v{version}\n\n"
                f"Хук: {remake.hook}\n\n{remake.script}\n\n"
                "Проверь текст. Озвучка и рендер ещё не запускались.",
                reply_markup=draft_keyboard(order.id),
                draft_version=version,
            )
            return False

        if order:
            self._order_card(
                order.id,
                OrderStatus.VOICING,
                "voice",
                f"🎙 Заказ #{order.id}\nСтатус: озвучиваю сценарий",
            )

        if report:
            report.stage("voice", meta.source_id)
        voice_result = self.voice.synthesize(path, remake)
        remake, voice_result, needs_reapproval = self._ensure_target_duration(
            path,
            meta,
            transcript,
            remake,
            voice_result,
            research_context=research_context,
            require_approval=bool(order),
        )
        if order and needs_reapproval:
            from src.telegram.topic_intake import draft_keyboard

            refreshed = self.db.get_order(order.id) or order
            version = max(1, refreshed.draft_version + 1)
            self._order_card(
                order.id,
                OrderStatus.DRAFT_READY,
                "draft_ready",
                f"📝 Заказ #{order.id} · сценарий v{version}\n\n"
                f"Хук: {remake.hook}\n\n{remake.script}\n\n"
                "Я скорректировал длину после пробной озвучки. Проверь новую версию перед рендером.",
                reply_markup=draft_keyboard(order.id),
                draft_version=version,
            )
            return False
        self.db.update_status(meta.source_id, JobStatus.VOICED)

        if order and self._order_cancelled(order.id):
            return False

        shot_clips: list[Path] = []
        if renderer_mode in ("faceless", "hybrid"):
            if order:
                self._order_card(
                    order.id,
                    OrderStatus.VISUALS,
                    "visuals",
                    f"🎞 Заказ #{order.id}\nСтатус: подбираю визуалы",
                )
            if report:
                report.stage("pexels", meta.source_id)
            shot_clips = self.pexels.download_shots(
                path,
                remake,
                topic=meta.title if meta.platform == "topic" else "",
            )

        if order:
            self._order_card(
                order.id,
                OrderStatus.RENDERING,
                "render",
                f"⚙️ Заказ #{order.id}\nСтатус: собираю финальное видео",
            )
        if report:
            report.stage("render", f"{renderer_mode}:{meta.source_id}")
        final = renderer.render(path, remake, voice_result, shot_clips)
        self.db.update_status(meta.source_id, JobStatus.RENDERED)

        out_dir = Path(today_output_dir(str(self.settings.output_dir)))
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(remake.title or meta.source_id)
        dest_video = out_dir / f"{slug}.mp4"
        shutil.copy2(final, dest_video)
        write_caption(out_dir, slug, remake.caption, remake.hashtags)
        logger.info("Output: %s", dest_video)
        if order:
            self.db.update_order(
                order.id,
                OrderStatus.RENDERING,
                current_stage="render",
                output_path=str(dest_video),
            )

        from src.publish.base import PublishMeta
        from src.publish.orchestrator import PublishOrchestrator

        meta_pub = PublishMeta(
            title=remake.title or remake.hook or slug,
            caption=remake.caption or "",
            hashtags=list(remake.hashtags or []),
            source_id=meta.source_id,
            order_id=meta.order_id,
            video_path=dest_video,
        )
        publishers = None
        if order:
            from src.publish.adapters_telegram_dm import TelegramDmPublisher

            # Telegram order delivery is a preview. External platforms require
            # the explicit "Publish" button from the ready card.
            publishers = [TelegramDmPublisher()]
        results = PublishOrchestrator(
            self.settings,
            publishers=publishers,
            notify=self._tg if self.settings.telegram_notify else None,
            report=report,
        ).publish_all(dest_video, meta_pub)
        if any(r.status == "ok" and r.platform == "telegram_dm" for r in results):
            self.db.update_status(meta.source_id, JobStatus.PUBLISHED)
        elif any(r.status == "ok" for r in results):
            self.db.update_status(meta.source_id, JobStatus.PUBLISHED)
        if order:
            self._order_card(
                order.id,
                OrderStatus.READY,
                "ready",
                f"✅ Заказ #{order.id}\nСтатус: готово\n\n"
                "Видео и текст публикации отправлены отдельным сообщением.",
                finished=True,
            )
        return True

    def _ensure_target_duration(
        self,
        path,
        meta,
        transcript,
        remake,
        voice_result,
        *,
        research_context=None,
        require_approval: bool = False,
    ):
        min_sec = self.settings.target_duration_min
        max_sec = self.settings.target_duration_max
        duration = voice_result.duration_sec

        if min_sec <= duration <= max_sec:
            return remake, voice_result, False

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
        remake = self.rewriter.rewrite(
            path, meta, transcript, duration_hint=hint, research_context=research_context
        )
        write_remake(path, remake)
        self.db.update_status(meta.source_id, JobStatus.REWRITTEN)
        if require_approval:
            return remake, voice_result, True
        return remake, self.voice.synthesize(path, remake), False


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
