"""VK group video upload (video.save → upload → wall.post)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from src.publish.base import PublishMeta, PublishResult
from src.publish.media_prep import clip_text, join_caption

logger = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"


class VkPublisher:
    name = "vk_video"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        if not getattr(settings, "publish_vk", False):
            return False
        return bool(settings.vk_access_token and settings.vk_group_id)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not getattr(settings, "publish_vk", False):
            return PublishResult.skipped(self.name, "PUBLISH_VK off")
        if not settings.vk_access_token or not settings.vk_group_id:
            return PublishResult.skipped(self.name, "missing VK_ACCESS_TOKEN / VK_GROUP_ID")
        if not video.exists():
            return PublishResult.failed(self.name, f"video not found: {video}")

        try:
            group_id = int(str(settings.vk_group_id).lstrip("-"))
            version = settings.vk_api_version or "5.199"
            title = clip_text(meta.title_or_stem(video.stem), 100)
            description = join_caption(meta.caption, meta.hashtags, max_len=5000)

            with httpx.Client(timeout=120.0) as client:
                save = self._api(
                    client,
                    "video.save",
                    {
                        "access_token": settings.vk_access_token,
                        "v": version,
                        "name": title,
                        "description": description,
                        "group_id": group_id,
                        "wallpost": 1,
                    },
                )
                upload_url = (save.get("response") or {}).get("upload_url")
                owner_id = (save.get("response") or {}).get("owner_id")
                video_id = (save.get("response") or {}).get("video_id")
                if not upload_url:
                    raise RuntimeError(f"video.save missing upload_url: {save}")

                with video.open("rb") as handle:
                    up = client.post(
                        upload_url,
                        files={"video_file": (video.name, handle, "video/mp4")},
                        timeout=600.0,
                    )
                up.raise_for_status()
                uploaded = up.json()
                if uploaded.get("error"):
                    raise RuntimeError(f"VK upload error: {uploaded}")

            url = ""
            if owner_id is not None and video_id is not None:
                url = f"https://vk.com/video{owner_id}_{video_id}"
            logger.info("VK video published: %s", url or uploaded)
            return PublishResult.ok(
                self.name,
                url=url,
                detail={"owner_id": owner_id, "video_id": video_id, "upload": uploaded},
            )
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))

    @staticmethod
    def _api(client: httpx.Client, method: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = client.post(f"{VK_API}/{method}", data=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(
                f"VK {method} error {err.get('error_code')}: {err.get('error_msg')}"
            )
        return data


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.telegram import send_message
    from src.publish.youtube import find_latest_output_video

    load_dotenv()
    parser = argparse.ArgumentParser(description="Upload latest Reel to VK group")
    parser.add_argument("video", nargs="?")
    args = parser.parse_args(argv)
    settings = load_settings()
    settings.publish_vk = True  # type: ignore[attr-defined]
    settings.publish_enabled = True  # type: ignore[attr-defined]

    pub = VkPublisher()
    video = Path(args.video) if args.video else find_latest_output_video(settings.output_dir)
    if video is None:
        print("No video in output/", file=sys.stderr)
        return 2
    meta = PublishMeta(title=video.stem.replace("-", " "), caption=video.stem)
    result = pub.publish(video, meta, settings)
    print(result.line())
    if settings.telegram_notify and settings.telegram_bot_token:
        try:
            send_message(settings.telegram_bot_token, settings.telegram_owner_chat_id, result.line())
        except Exception:
            pass
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
