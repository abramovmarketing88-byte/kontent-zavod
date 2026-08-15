"""Author welcome + soft reminders (channel / DM) for installers.

First pipeline start → always show welcome.
Later → rare nudges (every N successful runs or every D days).
Disable with AUTHOR_NUDGE=false.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUTHOR_NAME = "Александр Абрамов"
CHANNEL_URL = "https://t.me/Abramov_like"
CHANNEL_HANDLE = "@Abramov_like"
DM_URL = "https://t.me/Abramow191"
DM_HANDLE = "@Abramow191"
REPO_URL = "https://github.com/abramovmarketing88-byte/kontent-zavod"

# Soft cadence — not spam
REMIND_EVERY_RUNS = 8
REMIND_EVERY_DAYS = 7

WELCOME = f"""👋 Спасибо, что поставил Kontent Zavod!

Автор: {AUTHOR_NAME}
📢 Канал (трафик + нейросети): {CHANNEL_URL}
💬 Вопросы / внедрение / доработки: {DM_URL}

Если что-то не взлетит — пиши в личку, разберём."""

REMINDERS = [
    f"📢 Напоминалка: подпишись на канал автора — {CHANNEL_URL}\n"
    f"Там разборы трафика и нейросетей. Вопросы → {DM_URL}",
    f"🛠 Нужна доработка завода (Stories / YouTube / ниша)?\n"
    f"Напиши {DM_HANDLE}: {DM_URL}\n"
    f"Канал: {CHANNEL_URL}",
    f"💡 Идея или баг по Kontent Zavod?\n"
    f"Личка автора: {DM_URL}\n"
    f"Канал: {CHANNEL_HANDLE} → {CHANNEL_URL}",
    f"🔥 Если завод уже крутит ролики — загляни в канал {CHANNEL_HANDLE}\n"
    f"{CHANNEL_URL}\n"
    f"По кастомным фичам → {DM_URL}",
]


def _enabled() -> bool:
    return os.getenv("AUTHOR_NUDGE", "true").lower() in ("1", "true", "yes", "")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path(data_dir: Path) -> Path:
    return data_dir / "author_nudge.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "welcome_shown": False,
            "welcome_sent_tg": False,
            "successful_runs": 0,
            "last_nudge_at": "",
            "last_nudge_run": 0,
            "nudge_index": 0,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "welcome_shown": False,
            "welcome_sent_tg": False,
            "successful_runs": 0,
            "last_nudge_at": "",
            "last_nudge_run": 0,
            "nudge_index": 0,
        }


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def console_banner(text: str) -> None:
    bar = "=" * 56
    print(f"\n{bar}\n{text.strip()}\n{bar}\n", flush=True)


def maybe_welcome(
    data_dir: Path,
    *,
    send_telegram: Any | None = None,
) -> str | None:
    """Show first-install welcome once. Returns message if shown."""
    if not _enabled():
        return None
    path = _state_path(data_dir)
    state = _load_state(path)
    if state.get("welcome_shown"):
        return None

    console_banner(WELCOME)
    logger.info("Author welcome shown (first install)")

    if send_telegram is not None and not state.get("welcome_sent_tg"):
        try:
            send_telegram(WELCOME)
            state["welcome_sent_tg"] = True
        except Exception as exc:
            logger.warning("Author welcome Telegram failed: %s", exc)

    state["welcome_shown"] = True
    state["first_seen_at"] = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_state(path, state)
    return WELCOME


def note_successful_run(
    data_dir: Path,
    *,
    send_telegram: Any | None = None,
) -> str | None:
    """Bump run counter; occasionally remind about channel / DM."""
    if not _enabled():
        return None
    path = _state_path(data_dir)
    state = _load_state(path)
    # Ensure welcome happened at least once
    if not state.get("welcome_shown"):
        maybe_welcome(data_dir, send_telegram=send_telegram)
        state = _load_state(path)

    state["successful_runs"] = int(state.get("successful_runs") or 0) + 1
    runs = state["successful_runs"]
    last_run = int(state.get("last_nudge_run") or 0)
    last_at_raw = state.get("last_nudge_at") or ""
    due_by_runs = runs - last_run >= REMIND_EVERY_RUNS
    due_by_days = False
    if last_at_raw:
        try:
            last_at = datetime.strptime(last_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            due_by_days = (_utc_now() - last_at).days >= REMIND_EVERY_DAYS
        except ValueError:
            due_by_days = True
    else:
        due_by_days = runs >= REMIND_EVERY_RUNS

    msg: str | None = None
    if due_by_runs or due_by_days:
        idx = int(state.get("nudge_index") or 0) % len(REMINDERS)
        msg = REMINDERS[idx]
        console_banner(msg)
        if send_telegram is not None:
            try:
                send_telegram(msg)
            except Exception as exc:
                logger.warning("Author nudge Telegram failed: %s", exc)
        state["nudge_index"] = idx + 1
        state["last_nudge_run"] = runs
        state["last_nudge_at"] = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("Author nudge #%d sent (runs=%d)", idx + 1, runs)

    _save_state(path, state)
    return msg


def print_install_banner() -> None:
    """For bash install scripts (no state — always print once per script call)."""
    console_banner(WELCOME)
