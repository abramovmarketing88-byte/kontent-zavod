"""Post Telegram Stories on behalf of a managed Business account (postStory)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import httpx

from src.ffmpeg_bin import get_ffmpeg, probe_duration
from src.publish.youtube import find_latest_output_video

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
STORY_W = 720
STORY_H = 1280
ACTIVE_PERIODS = (21600, 43200, 86400, 172800)


class TelegramStoryError(RuntimeError):
    pass


def _api(token: str, method: str) -> str:
    return API.format(token=token, method=method)


def discover_business_connection_id(bot_token: str) -> str | None:
    """Find an enabled business connection from recent getUpdates."""
    if not bot_token:
        return None
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(
            _api(bot_token, "getUpdates"),
            params={"limit": 100, "allowed_updates": json.dumps(["business_connection", "message"])},
        )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("getUpdates failed: %s", data)
        return None

    found: str | None = None
    for update in data.get("result") or []:
        bc = update.get("business_connection")
        if not bc:
            continue
        if not bc.get("is_enabled", True):
            continue
        rights = bc.get("rights") or {}
        # If rights present and stories explicitly false — skip
        if "can_manage_stories" in rights and not rights.get("can_manage_stories"):
            logger.warning(
                "Business connection %s lacks can_manage_stories",
                bc.get("id"),
            )
            continue
        found = bc.get("id") or found
        logger.info(
            "Found business_connection_id=%s user=%s",
            found,
            (bc.get("user") or {}).get("username") or (bc.get("user") or {}).get("id"),
        )

        # Prefer one that can manage stories
        if rights.get("can_manage_stories"):
            return found

    if found:
        return found

    # Fallback: any message carrying business_connection_id
    for update in data.get("result") or []:
        msg = update.get("message") or update.get("business_message") or {}
        cid = msg.get("business_connection_id")
        if cid:
            logger.info("Found business_connection_id from message: %s", cid)
            return cid
    return None


def prepare_story_video(src: Path, dest: Path, *, max_duration: float = 60.0) -> Path:
    """Re-encode to Telegram story specs: 720x1280, H.265, keyframe/sec."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = min(probe_duration(src) or max_duration, max_duration)
    vf = (
        f"scale={STORY_W}:{STORY_H}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={STORY_W}:{STORY_H},setsar=1,fps=30"
    )
    cmd = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-t",
        f"{duration:.2f}",
        "-vf",
        vf,
        "-c:v",
        "libx265",
        "-tag:v",
        "hvc1",
        "-pix_fmt",
        "yuv420p",
        "-x265-params",
        "keyint=30:min-keyint=30:scenecut=0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: some slim images lack libx265 — try libx264 (may be rejected by TG)
        logger.warning("libx265 encode failed, trying libx264: %s", result.stderr[-300:])
        cmd_h264 = [
            get_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-t",
            f"{duration:.2f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-keyint_min",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
        result2 = subprocess.run(cmd_h264, capture_output=True, text=True)
        if result2.returncode != 0:
            raise TelegramStoryError(
                f"story re-encode failed: {result2.stderr[-400:] or result.stderr[-400:]}"
            )
    if not dest.exists() or dest.stat().st_size < 1000:
        raise TelegramStoryError(f"story video missing/empty: {dest}")
    logger.info("Prepared story video %s (%d bytes, %.1fs)", dest.name, dest.stat().st_size, duration)
    return dest


def post_story_video(
    bot_token: str,
    business_connection_id: str,
    video_path: Path,
    *,
    caption: str = "",
    active_period: int = 86400,
    post_to_chat_page: bool = False,
) -> dict[str, Any]:
    if not bot_token:
        raise TelegramStoryError("TELEGRAM_BOT_TOKEN not set")
    if not business_connection_id:
        raise TelegramStoryError(
            "TELEGRAM_BUSINESS_CONNECTION_ID missing — "
            "set it or ensure getUpdates has a business_connection update"
        )
    if not video_path.exists():
        raise TelegramStoryError(f"Video not found: {video_path}")
    if active_period not in ACTIVE_PERIODS:
        active_period = 86400

    duration = min(probe_duration(video_path) or 30.0, 60.0)
    content = {
        "type": "video",
        "video": "attach://story_video",
        "duration": round(duration, 2),
        "cover_frame_timestamp": 0.0,
    }
    data = {
        "business_connection_id": business_connection_id,
        "content": json.dumps(content),
        "active_period": str(active_period),
    }
    if caption:
        data["caption"] = caption[:2048]
    if post_to_chat_page:
        data["post_to_chat_page"] = "true"

    with video_path.open("rb") as handle:
        resp = httpx.post(
            _api(bot_token, "postStory"),
            data=data,
            files={"story_video": (video_path.name, handle, "video/mp4")},
            timeout=300.0,
        )
    payload = resp.json()
    if not payload.get("ok"):
        raise TelegramStoryError(f"postStory failed: {payload}")
    story = payload.get("result") or {}
    logger.info(
        "Posted Telegram story id=%s chat=%s",
        story.get("id"),
        (story.get("chat") or {}).get("id"),
    )
    return story


def post_latest_as_story(
    *,
    bot_token: str,
    business_connection_id: str,
    output_dir: Path,
    work_dir: Path,
    caption: str = "",
    active_period: int = 86400,
) -> dict[str, Any]:
    src = find_latest_output_video(output_dir)
    if src is None:
        raise TelegramStoryError("No video in output/ to post as story")
    prepared = work_dir / "story_720x1280.mp4"
    prepare_story_video(src, prepared)
    story = post_story_video(
        bot_token,
        business_connection_id,
        prepared,
        caption=caption or src.stem.replace("-", " "),
        active_period=active_period,
    )
    return {"source": str(src), "prepared": str(prepared), "story": story}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.telegram import send_message

    load_dotenv()
    parser = argparse.ArgumentParser(description="Post latest Reel as Telegram Business story")
    parser.add_argument("video", nargs="?", help="Source mp4 (default: newest in output/)")
    parser.add_argument("--caption", default="")
    parser.add_argument("--active-period", type=int, default=86400)
    args = parser.parse_args(argv)

    settings = load_settings()
    conn = settings.telegram_business_connection_id.strip()
    if not conn:
        conn = discover_business_connection_id(settings.telegram_bot_token) or ""
        if conn:
            cache = settings.data_dir / "business_connection.id"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(conn + "\n", encoding="utf-8")
            logger.info("Cached business_connection_id -> %s", cache)

    if not conn:
        cached = settings.data_dir / "business_connection.id"
        if cached.exists():
            conn = cached.read_text(encoding="utf-8").strip()

    try:
        if args.video:
            src = Path(args.video)
            if not src.exists():
                raise TelegramStoryError(f"Video not found: {src}")
            prepared = settings.data_dir / "story_720x1280.mp4"
            prepare_story_video(src, prepared)
            story = post_story_video(
                settings.telegram_bot_token,
                conn,
                prepared,
                caption=args.caption or src.stem.replace("-", " "),
                active_period=args.active_period,
            )
            result = {"source": str(src), "story": story}
        else:
            result = post_latest_as_story(
                bot_token=settings.telegram_bot_token,
                business_connection_id=conn,
                output_dir=settings.output_dir,
                work_dir=settings.data_dir,
                caption=args.caption,
                active_period=args.active_period,
            )
    except TelegramStoryError as exc:
        print(f"STORY_FAILED: {exc}", file=sys.stderr)
        if settings.telegram_notify and settings.telegram_bot_token and settings.telegram_owner_chat_id:
            try:
                send_message(
                    settings.telegram_bot_token,
                    settings.telegram_owner_chat_id,
                    f"❌ Telegram Story failed\n{exc}",
                )
            except Exception:
                pass
        return 1

    story = result.get("story") or {}
    msg = (
        f"✅ Telegram Story (Business)\n"
        f"source={result.get('source')}\n"
        f"story_id={story.get('id')}\n"
        f"chat={(story.get('chat') or {}).get('id')}"
    )
    print(msg)
    if settings.telegram_notify and settings.telegram_bot_token and settings.telegram_owner_chat_id:
        try:
            send_message(
                settings.telegram_bot_token,
                settings.telegram_owner_chat_id,
                msg,
            )
        except Exception as exc:
            print(f"telegram notify failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
