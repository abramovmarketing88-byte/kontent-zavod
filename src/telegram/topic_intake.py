"""Telegram UX for durable Reels orders, approvals, revisions and status."""

from __future__ import annotations

import argparse
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from src.analyze.transcriber import transcribe_audio
from src.config import Settings, load_settings
from src.db import Database
from src.models import ContentOrder, OrderStatus
from src.publish.telegram import send_message

logger = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"

HELP_TEXT = (
    "🎬 Kontent Zavod\n\n"
    "Создаю вертикальное видео по теме: выбираешь формат, затем проверяешь сценарий. "
    "Озвучка и рендер начнутся только после твоего подтверждения.\n\n"
    "Быстрые команды:\n"
    "• /new — новый ролик\n"
    "• /topic тема — создать заказ сразу\n"
    "• /orders — последние заказы\n"
    "• /status номер — статус заказа\n"
    "• /cancel номер — отменить заказ\n"
    "• /retry номер — повторить упавший заказ\n"
    "• /help — эта справка"
)

STATUS_LABELS = {
    OrderStatus.QUEUED: "В очереди",
    OrderStatus.PROCESSING: "В работе",
    OrderStatus.DRAFT_READY: "Сценарий ждёт подтверждения",
    OrderStatus.APPROVED: "Сценарий принят",
    OrderStatus.REVISION_REQUESTED: "Правлю сценарий",
    OrderStatus.VOICING: "Озвучиваю",
    OrderStatus.VISUALS: "Подбираю визуалы",
    OrderStatus.RENDERING: "Собираю видео",
    OrderStatus.READY: "Готово",
    OrderStatus.PUBLISH_REQUESTED: "Ждёт публикации",
    OrderStatus.PUBLISHING: "Публикую",
    OrderStatus.PUBLISHED: "Опубликовано",
    OrderStatus.FAILED: "Нужна помощь",
    OrderStatus.CANCELLED: "Отменён",
}


def main_menu() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🎬 Создать Reels", "callback_data": "menu:new"}],
            [
                {"text": "📋 Мои заказы", "callback_data": "menu:orders"},
                {"text": "❓ Помощь", "callback_data": "menu:help"},
            ],
        ]
    }


def confirm_topic_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "🎬 Создать из сообщения", "callback_data": "input:confirm"},
            {"text": "Отмена", "callback_data": "input:cancel"},
        ]]
    }


def format_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "✨ Автоматически", "callback_data": "input:format:auto"}],
            [
                {"text": "🎞 Faceless", "callback_data": "input:format:faceless"},
                {"text": "👤 С аватаром", "callback_data": "input:format:heygen"},
            ],
            [{"text": "🎬 Гибрид", "callback_data": "input:format:hybrid"}],
        ]
    }


def draft_keyboard(order_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "✅ Принять и собрать", "callback_data": f"order:approve:{order_id}"}],
            [
                {"text": "✏️ Изменить", "callback_data": f"order:edit:{order_id}"},
                {"text": "🗑 Отменить", "callback_data": f"order:cancel:{order_id}"},
            ],
        ]
    }


def failed_keyboard(order_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "🔄 Повторить", "callback_data": f"order:retry:{order_id}"},
            {"text": "🗑 Отменить", "callback_data": f"order:cancel:{order_id}"},
        ]]
    }


def format_topic_brief(topic: str) -> str:
    raw = " ".join(topic.split()).strip()
    if not raw:
        return ""
    title = raw[0].upper() + raw[1:]
    body = (
        f"Сделай Reels на тему: {raw}.\n"
        "Перед сценарием — проанализируй интернет: факты, тренды, вирусные углы.\n"
        "Тон мотивирующий и живой. Структура: хук → мысль → 2 примера → CTA.\n"
        "30–40 секунд, русский."
    )
    return f"{title}\n\n{body}"


def build_topic_file(topic: str, *, run_id: str | None = None) -> str:
    """Legacy file format retained for manual/SSH compatibility."""
    rid = (run_id or uuid.uuid4().hex)[:12]
    return f"#run:{rid}\n#telegram\n{format_topic_brief(topic)}\n"


def parse_topic_text(text: str) -> str | None:
    """Extract a topic only from the explicit /topic command."""
    text = (text or "").strip()
    if not text or not text.startswith("/topic"):
        return None
    rest = text[6:].strip()
    if rest.startswith("@"):
        parts = rest.split(None, 1)
        rest = parts[1] if len(parts) > 1 else ""
    return rest.strip() or None


def bump_run_once_trigger(root: Path) -> str:
    trigger = root / "triggers" / "run-once.id"
    trigger.parent.mkdir(parents=True, exist_ok=True)
    new_id = uuid.uuid4().hex
    trigger.write_text(new_id + "\n", encoding="utf-8")
    return new_id


def queue_topic(
    settings: Settings,
    topic: str,
    *,
    owner_chat_id: str | None = None,
) -> tuple[str, str]:
    """Create a durable SQLite order and wake the one-off worker."""
    db = Database(settings.db_path)
    order = db.create_order(
        owner_chat_id or str(settings.telegram_owner_chat_id),
        topic,
        format_topic_brief(topic),
        renderer="auto",
    )
    trigger_id = bump_run_once_trigger(settings.root)
    logger.info("Queued order=%s trigger=%s title=%r", order.id, trigger_id, topic[:80])
    return order.id, trigger_id


def _api(token: str, method: str) -> str:
    return API.format(token=token, method=method)


def _offset_path(settings: Settings) -> Path:
    return settings.data_dir / "telegram_topic.offset"


def _load_offset(settings: Settings) -> int:
    path = _offset_path(settings)
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return 0


def _save_offset(settings: Settings, offset: int) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _offset_path(settings).write_text(str(offset) + "\n", encoding="utf-8")


def _download_telegram_file(token: str, file_id: str, dest: Path) -> Path:
    with httpx.Client(timeout=120.0) as client:
        meta = client.get(_api(token, "getFile"), params={"file_id": file_id})
        meta.raise_for_status()
        data = meta.json()
        if not data.get("ok"):
            raise RuntimeError("Telegram не вернул файл")
        file_path = data["result"]["file_path"]
        resp = client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
    return dest


def _transcribe_voice(settings: Settings, token: str, file_id: str) -> str:
    tmp = settings.data_dir / "telegram_voice"
    tmp.mkdir(parents=True, exist_ok=True)
    audio_path = tmp / f"{uuid.uuid4().hex}.ogg"
    try:
        _download_telegram_file(token, file_id, audio_path)
        result = transcribe_audio(settings, audio_path)
        text = (result.text or "").strip()
        if not text:
            raise RuntimeError("пустое распознавание")
        return text
    finally:
        audio_path.unlink(missing_ok=True)


def _owner_chat_id(settings: Settings) -> str:
    return str(settings.telegram_owner_chat_id or "").strip()


def _is_owner(settings: Settings, chat_id: str | int | None) -> bool:
    return bool(chat_id is not None and str(chat_id) == _owner_chat_id(settings))


def _reply(
    settings: Settings,
    chat_id: str | int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> dict:
    return send_message(
        settings.telegram_bot_token,
        str(chat_id),
        text,
        reply_markup=reply_markup,
    )


def _answer_callback(settings: Settings, callback_id: str, text: str = "") -> None:
    try:
        httpx.post(
            _api(settings.telegram_bot_token, "answerCallbackQuery"),
            json={"callback_query_id": callback_id, "text": text[:200]},
            timeout=30.0,
        ).raise_for_status()
    except Exception as exc:
        logger.warning("answerCallbackQuery failed: %s", exc)


def _format_order(order: ContentOrder) -> str:
    label = STATUS_LABELS.get(order.status, order.status.value)
    error = f"\nПричина: {order.error_user_text}" if order.error_user_text else ""
    return f"#{order.id} · {label}\n{order.topic[:180]}{error}"


def _show_orders(settings: Settings, db: Database, chat_id: str | int) -> None:
    orders = db.list_orders(str(chat_id), limit=10)
    if not orders:
        _reply(settings, chat_id, "Заказов пока нет.", reply_markup=main_menu())
        return
    _reply(
        settings,
        chat_id,
        "📋 Последние заказы\n\n" + "\n\n".join(_format_order(o) for o in orders),
        reply_markup=main_menu(),
    )


def _resolve_order(db: Database, chat_id: str | int, raw_id: str) -> ContentOrder | None:
    raw_id = raw_id.strip().lstrip("#")
    matches = [o for o in db.list_orders(str(chat_id), 50) if o.id.startswith(raw_id)]
    return matches[0] if len(matches) == 1 else None


def _create_order(
    settings: Settings,
    db: Database,
    chat_id: str | int,
    topic: str,
    *,
    renderer: str = "auto",
    idempotency_key: str = "",
) -> bool:
    topic = " ".join(topic.split()).strip()
    if len(topic) < 3:
        _reply(settings, chat_id, "Тема слишком короткая. Добавь хотя бы несколько слов.")
        return False
    if len(topic) > 500:
        _reply(settings, chat_id, "Тема длиннее 500 символов. Сократи основную мысль.")
        return False
    existing = db.get_order_by_idempotency(idempotency_key)
    if existing is not None:
        # The previous attempt may have crashed after DB commit but before wake-up.
        bump_run_once_trigger(settings.root)
        return False
    order = db.create_order(
        str(chat_id),
        topic,
        format_topic_brief(topic),
        renderer=renderer,
        idempotency_key=idempotency_key,
    )
    # Wake the worker before network replies: a Telegram outage must not strand
    # an order that is already durably committed.
    bump_run_once_trigger(settings.root)
    renderer_label = {
        "auto": "автоматически",
        "faceless": "faceless",
        "heygen": "с аватаром",
        "hybrid": "гибрид",
    }.get(renderer, renderer)
    result = _reply(
        settings,
        chat_id,
        f"🕓 Заказ #{order.id}\nСтатус: в очереди\nФормат: {renderer_label}\n\n{topic}\n\n"
        "Когда сценарий будет готов, я пришлю его на согласование.",
        reply_markup={
            "inline_keyboard": [[
                {"text": "📋 Мои заказы", "callback_data": "menu:orders"},
                {"text": "🗑 Отменить", "callback_data": f"order:cancel:{order.id}"},
            ]]
        },
    )
    try:
        db.set_status_message(order.id, int(result["result"]["message_id"]))
    except (KeyError, TypeError, ValueError):
        logger.warning("No status message id for order %s", order.id)
    db.set_session(str(chat_id), "idle")
    return True


def _handle_command(
    settings: Settings,
    db: Database,
    chat_id: str | int,
    text: str,
    *,
    idempotency_key: str = "",
) -> bool:
    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command in ("/start", "/help"):
        db.set_session(str(chat_id), "idle")
        _reply(settings, chat_id, HELP_TEXT, reply_markup=main_menu())
    elif command == "/new":
        db.set_session(str(chat_id), "awaiting_topic")
        _reply(settings, chat_id, "Напиши тему будущего ролика текстом или голосовым.")
    elif command == "/topic":
        topic = parse_topic_text(text)
        if not topic:
            _reply(settings, chat_id, "После /topic укажи тему. Например: /topic 5 ошибок на Авито")
        else:
            return _create_order(
                settings, db, chat_id, topic, idempotency_key=idempotency_key
            )
    elif command == "/orders":
        _show_orders(settings, db, chat_id)
    elif command == "/status":
        order = _resolve_order(db, chat_id, arg)
        _reply(settings, chat_id, _format_order(order) if order else "Заказ не найден. Открой /orders.")
    elif command == "/cancel":
        order = _resolve_order(db, chat_id, arg)
        if order and db.cancel_order(order.id, str(chat_id)):
            _reply(settings, chat_id, f"Заказ #{order.id} отменён.", reply_markup=main_menu())
        else:
            _reply(settings, chat_id, "Не удалось отменить заказ: он не найден или уже выполняется.")
    elif command == "/retry":
        order = _resolve_order(db, chat_id, arg)
        if order and db.retry_order(order.id, str(chat_id)):
            bump_run_once_trigger(settings.root)
            _reply(settings, chat_id, f"Заказ #{order.id} снова поставлен в очередь.")
        else:
            _reply(settings, chat_id, "Повтор доступен только для упавшего заказа из /orders.")
    else:
        _reply(settings, chat_id, "Неизвестная команда. Открой /help.", reply_markup=main_menu())
    return False


def _handle_callback(
    settings: Settings,
    db: Database,
    callback: dict,
    *,
    idempotency_key: str = "",
) -> bool:
    callback_id = str(callback.get("id") or "")
    msg = callback.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not _is_owner(settings, chat_id):
        _answer_callback(settings, callback_id, "Недоступно")
        return False
    data = str(callback.get("data") or "")
    _answer_callback(settings, callback_id)

    if data == "menu:new":
        db.set_session(str(chat_id), "awaiting_topic")
        _reply(settings, chat_id, "Напиши тему будущего ролика текстом или голосовым.")
        return False
    if data == "menu:orders":
        _show_orders(settings, db, chat_id)
        return False
    if data == "menu:help":
        _reply(settings, chat_id, HELP_TEXT, reply_markup=main_menu())
        return False
    if data == "input:cancel":
        db.set_session(str(chat_id), "idle")
        _reply(settings, chat_id, "Сообщение не стало заказом.", reply_markup=main_menu())
        return False
    if data == "input:confirm":
        pending = db.get_session(str(chat_id)).get("pending_text", "")
        if pending:
            db.set_session(str(chat_id), "awaiting_format", pending_text=pending)
            _reply(settings, chat_id, "Выбери формат ролика:", reply_markup=format_keyboard())
            return False
        _reply(settings, chat_id, "Тема устарела. Нажми «Создать Reels» ещё раз.")
        return False
    if data.startswith("input:format:"):
        renderer = data.rsplit(":", 1)[-1]
        if renderer not in ("auto", "faceless", "heygen", "hybrid"):
            return False
        pending = db.get_session(str(chat_id)).get("pending_text", "")
        if not pending:
            _reply(settings, chat_id, "Тема устарела. Нажми «Создать Reels» ещё раз.")
            return False
        return _create_order(
            settings,
            db,
            chat_id,
            pending,
            renderer=renderer,
            idempotency_key=idempotency_key,
        )

    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "order":
        return False
    action, order_id = parts[1], parts[2]
    order = _resolve_order(db, chat_id, order_id)
    if order is None:
        _reply(settings, chat_id, "Заказ не найден. Открой /orders.")
        return False
    if action == "approve":
        if db.approve_order(order.id, str(chat_id)):
            bump_run_once_trigger(settings.root)
            _reply(settings, chat_id, f"✅ Сценарий заказа #{order.id} принят. Запускаю озвучку и сборку.")
        else:
            _reply(settings, chat_id, "Сценарий уже принят или состояние заказа изменилось.")
    elif action == "edit":
        if order.status not in (OrderStatus.DRAFT_READY, OrderStatus.READY):
            _reply(settings, chat_id, "Правка сейчас недоступна. Проверь /orders.")
        else:
            db.set_session(str(chat_id), "awaiting_revision", active_order_id=order.id)
            _reply(
                settings,
                chat_id,
                f"Напиши одним сообщением, что изменить в сценарии заказа #{order.id}.\n"
                "Например: «Сделай хук жёстче и добавь CTA написать слово АУДИТ».",
            )
    elif action == "cancel":
        ok = db.cancel_order(order.id, str(chat_id))
        _reply(settings, chat_id, "Заказ отменён." if ok else "Уже нельзя отменить: заказ выполняется или завершён.")
    elif action == "retry":
        if db.retry_order(order.id, str(chat_id)):
            bump_run_once_trigger(settings.root)
            _reply(settings, chat_id, f"🔄 Заказ #{order.id} снова поставлен в очередь.")
        else:
            _reply(settings, chat_id, "Повтор доступен только для упавшего заказа.")
    elif action == "publish":
        if db.request_publish(order.id, str(chat_id)):
            bump_run_once_trigger(settings.root)
            _reply(settings, chat_id, f"📣 Публикация заказа #{order.id} запущена на подключённые площадки.")
        else:
            _reply(settings, chat_id, "Публикация недоступна: видео ещё не готово или уже отправляется.")
    return False


def _extract_message(update: dict) -> dict | None:
    for key in ("message", "edited_message", "business_message"):
        msg = update.get(key)
        if msg:
            return msg
    return None


def process_updates(settings: Settings, *, long_poll_timeout: int = 0) -> int:
    """Process one Telegram update batch. Returns newly created order count."""
    token = (settings.telegram_bot_token or "").strip()
    owner = _owner_chat_id(settings)
    if not token or not owner or not settings.telegram_topic_intake:
        return 0
    db = Database(settings.db_path)
    db.reclaim_stale_orders()
    offset = _load_offset(settings)
    params = {
        "offset": offset,
        "timeout": max(0, min(long_poll_timeout, 50)),
        "allowed_updates": json.dumps(
            ["message", "edited_message", "business_message", "callback_query"]
        ),
    }
    with httpx.Client(timeout=max(60.0, long_poll_timeout + 10.0)) as client:
        resp = client.get(_api(token, "getUpdates"), params=params)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        logger.warning("getUpdates failed: %s", data)
        return 0

    created = 0
    max_update_id = offset
    for update in data.get("result") or []:
        update_id = int(update.get("update_id", 0))
        max_update_id = max(max_update_id, update_id + 1)
        callback = update.get("callback_query")
        if callback:
            if _handle_callback(
                settings,
                db,
                callback,
                idempotency_key=f"telegram:{update_id}",
            ):
                created += 1
            continue
        msg = _extract_message(update)
        if not msg:
            continue
        chat_id = (msg.get("chat") or {}).get("id")
        if not _is_owner(settings, chat_id):
            continue
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if text.startswith("/"):
            if _handle_command(
                settings,
                db,
                chat_id,
                text,
                idempotency_key=f"telegram:{update_id}",
            ):
                created += 1
            continue

        session = db.get_session(str(chat_id))
        state = session.get("state", "idle")
        voice = msg.get("voice") or msg.get("video_note")
        if voice:
            if state != "awaiting_topic":
                _reply(settings, chat_id, "Сначала нажми «Создать Reels», затем отправь голосовое.", reply_markup=main_menu())
                continue
            try:
                text = _transcribe_voice(settings, token, voice["file_id"])
                _reply(settings, chat_id, f"🎤 Распознал тему: «{text}»")
            except Exception as exc:
                logger.exception("Voice topic failed: %s", exc)
                _reply(settings, chat_id, "Не смог распознать голосовое. Напиши тему текстом.")
                continue
        if not text:
            continue
        if state == "awaiting_topic":
            topic = " ".join(text.split()).strip()
            if len(topic) < 3 or len(topic) > 500:
                _reply(settings, chat_id, "Тема должна содержать от 3 до 500 символов.")
                continue
            db.set_session(str(chat_id), "awaiting_format", pending_text=topic)
            _reply(settings, chat_id, "Выбери формат ролика:", reply_markup=format_keyboard())
        elif state == "awaiting_revision":
            order_id = session.get("active_order_id", "")
            if db.request_revision(order_id, str(chat_id), text):
                db.set_session(str(chat_id), "idle")
                bump_run_once_trigger(settings.root)
                _reply(settings, chat_id, f"✏️ Правки для заказа #{order_id} приняты. Готовлю новую версию сценария.")
            else:
                db.set_session(str(chat_id), "idle")
                _reply(settings, chat_id, "Не удалось применить правку: состояние заказа изменилось.")
        else:
            db.set_session(str(chat_id), "confirm_topic", pending_text=text)
            _reply(
                settings,
                chat_id,
                "Это похоже на тему ролика. Создать из сообщения новый заказ?",
                reply_markup=confirm_topic_keyboard(),
            )

    if max_update_id > offset:
        _save_offset(settings, max_update_id)
    return created


def run_loop(settings: Settings) -> None:
    logger.info("Telegram bot long polling started")
    while True:
        try:
            process_updates(settings, long_poll_timeout=25)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            logger.exception("Telegram polling failed: %s", exc)
            time.sleep(3)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Kontent Zavod Telegram UX")
    parser.add_argument("--loop", action="store_true", help="Run dedicated long-polling bot")
    args = parser.parse_args()
    settings = load_settings()
    if args.loop:
        run_loop(settings)
    else:
        n = process_updates(settings)
        if n:
            logger.info("Queued %d order(s) from Telegram", n)


if __name__ == "__main__":
    main()
