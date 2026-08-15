"""TikTok Content Posting API (inbox / direct post when approved)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from src.publish.base import PublishMeta, PublishResult
from src.publish.media_prep import clip_text, join_caption

logger = logging.getLogger(__name__)

TIKTOK_API = "https://open.tiktokapis.com"


class TikTokPublisher:
    name = "tiktok"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        if not getattr(settings, "publish_tiktok", False):
            return False
        return bool(settings.tiktok_access_token)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not getattr(settings, "publish_tiktok", False):
            return PublishResult.skipped(self.name, "PUBLISH_TIKTOK off")
        if not settings.tiktok_access_token:
            return PublishResult.skipped(self.name, "missing TIKTOK_ACCESS_TOKEN")
        if not video.exists():
            return PublishResult.failed(self.name, f"video not found: {video}")

        caption = join_caption(meta.caption or meta.title, meta.hashtags, max_len=2200)
        title = clip_text(meta.title_or_stem(video.stem), 150)
        token = settings.tiktok_access_token
        size = video.stat().st_size

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                # Inbox upload init (works before full direct-post audit)
                init = client.post(
                    f"{TIKTOK_API}/v2/post/publish/inbox/video/init/",
                    headers=headers,
                    json={
                        "source_info": {
                            "source": "FILE_UPLOAD",
                            "video_size": size,
                            "chunk_size": size,
                            "total_chunk_count": 1,
                        }
                    },
                )
                init_data = init.json()
                if init.status_code >= 400 or (init_data.get("error") or {}).get("code") not in (
                    None,
                    "ok",
                    "success",
                    0,
                    "0",
                ):
                    # Some responses use error.code == "ok"
                    err = init_data.get("error") or init_data
                    if isinstance(err, dict) and str(err.get("code", "")).lower() in (
                        "ok",
                        "success",
                        "0",
                    ):
                        pass
                    elif init.status_code < 400 and (init_data.get("data") or {}).get(
                        "publish_id"
                    ):
                        pass
                    else:
                        raise RuntimeError(f"TikTok init failed: {init_data}")

                data = init_data.get("data") or {}
                publish_id = data.get("publish_id")
                upload_url = data.get("upload_url")
                if not publish_id or not upload_url:
                    raise RuntimeError(f"TikTok init missing publish_id/upload_url: {init_data}")

                with video.open("rb") as handle:
                    put = client.put(
                        upload_url,
                        content=handle,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(size),
                            "Content-Range": f"bytes 0-{size - 1}/{size}",
                        },
                        timeout=600.0,
                    )
                if put.status_code not in (200, 201, 204):
                    raise RuntimeError(
                        f"TikTok upload failed ({put.status_code}): {put.text[:300]}"
                    )

                logger.info(
                    "TikTok inbox upload ok publish_id=%s title=%s", publish_id, title
                )
                return PublishResult.ok(
                    self.name,
                    detail={
                        "publish_id": publish_id,
                        "mode": "inbox",
                        "caption": caption[:200],
                        "note": "Video sent to TikTok inbox — open app to post",
                    },
                )
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.youtube import find_latest_output_video

    load_dotenv()
    parser = argparse.ArgumentParser(description="Upload latest Reel to TikTok inbox")
    parser.add_argument("video", nargs="?")
    args = parser.parse_args(argv)
    settings = load_settings()
    settings.publish_tiktok = True  # type: ignore[attr-defined]
    settings.publish_enabled = True  # type: ignore[attr-defined]
    video = Path(args.video) if args.video else find_latest_output_video(settings.output_dir)
    if video is None:
        print("No video in output/", file=sys.stderr)
        return 2
    result = TikTokPublisher().publish(
        video, PublishMeta(title=video.stem, caption=video.stem), settings
    )
    print(result.line())
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
