"""Instagram Reels via Graph API (Business / Creator)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from src.publish.base import PublishMeta, PublishResult
from src.publish.media_prep import join_caption

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"


class InstagramReelsPublisher:
    name = "instagram_reels"

    def enabled(self, settings: Any) -> bool:
        if not getattr(settings, "publish_enabled", True):
            return False
        if not getattr(settings, "publish_instagram", False):
            return False
        return bool(settings.instagram_access_token and settings.instagram_user_id)

    def publish(self, video: Path, meta: PublishMeta, settings: Any) -> PublishResult:
        if not getattr(settings, "publish_instagram", False):
            return PublishResult.skipped(self.name, "PUBLISH_INSTAGRAM off")
        if not settings.instagram_access_token or not settings.instagram_user_id:
            return PublishResult.skipped(
                self.name, "missing INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID"
            )
        if not video.exists():
            return PublishResult.failed(self.name, f"video not found: {video}")

        # Graph Reels require a publicly reachable video_url OR resumable upload.
        # We use resumable rupload to graph (hosted binary).
        caption = join_caption(meta.caption, meta.hashtags, max_len=2200)
        token = settings.instagram_access_token
        ig_user = settings.instagram_user_id

        try:
            with httpx.Client(timeout=120.0) as client:
                # 1) Create reel container with file upload session via video_file binary
                # Official path: POST /{ig-user-id}/media with media_type=REELS + video_url
                # For local files without public URL: use rupload + video_file in some flows.
                # Monday-ready: prefer INSTAGRAM_VIDEO_PUBLIC_BASE_URL + filename, else try
                # resumable upload endpoint.
                video_url = getattr(settings, "instagram_video_public_url", "") or ""
                if not video_url and settings.instagram_public_base_url:
                    # Expect operator to expose output/ via CDN; pass absolute path name
                    video_url = (
                        settings.instagram_public_base_url.rstrip("/") + "/" + video.name
                    )

                if video_url:
                    create = client.post(
                        f"{GRAPH}/{ig_user}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": video_url,
                            "caption": caption,
                            "share_to_feed": "true",
                            "access_token": token,
                        },
                    )
                else:
                    # Resumable upload (session start) — works when Meta accepts file upload
                    size = video.stat().st_size
                    session = client.post(
                        f"https://rupload.facebook.com/video-upload/v21.0/{ig_user}",
                        headers={
                            "Authorization": f"OAuth {token}",
                            "offset": "0",
                            "file_size": str(size),
                            "Content-Type": "application/octet-stream",
                        },
                        content=video.read_bytes(),
                        timeout=600.0,
                    )
                    if session.status_code >= 400:
                        return PublishResult.skipped(
                            self.name,
                            "no public video URL — set INSTAGRAM_PUBLIC_BASE_URL "
                            f"or host the file; rupload status={session.status_code}: "
                            f"{session.text[:200]}",
                        )
                    handle = (session.json() or {}).get("h") or (session.json() or {}).get(
                        "video_id"
                    )
                    if not handle:
                        return PublishResult.failed(
                            self.name, f"rupload missing handle: {session.text[:300]}"
                        )
                    create = client.post(
                        f"{GRAPH}/{ig_user}/media",
                        data={
                            "media_type": "REELS",
                            "upload_type": "resumable",
                            "video_file_token": handle if isinstance(handle, str) else str(handle),
                            "caption": caption,
                            "share_to_feed": "true",
                            "access_token": token,
                        },
                    )

                data = create.json()
                if create.status_code >= 400 or data.get("error"):
                    err = (data.get("error") or {}).get("message") or create.text[:300]
                    raise RuntimeError(f"create container failed: {err}")
                creation_id = data.get("id")
                if not creation_id:
                    raise RuntimeError(f"no creation_id: {data}")

                # 2) Wait until FINISHED
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    st = client.get(
                        f"{GRAPH}/{creation_id}",
                        params={
                            "fields": "status_code,status",
                            "access_token": token,
                        },
                    )
                    payload = st.json()
                    code = (payload.get("status_code") or "").upper()
                    if code in ("FINISHED", "PUBLISHED"):
                        break
                    if code in ("ERROR", "EXPIRED"):
                        raise RuntimeError(f"container status={code}: {payload}")
                    time.sleep(5)
                else:
                    raise RuntimeError("container processing timeout")

                # 3) Publish
                pub = client.post(
                    f"{GRAPH}/{ig_user}/media_publish",
                    data={"creation_id": creation_id, "access_token": token},
                )
                pub_data = pub.json()
                if pub.status_code >= 400 or pub_data.get("error"):
                    err = (pub_data.get("error") or {}).get("message") or pub.text[:300]
                    raise RuntimeError(f"media_publish failed: {err}")
                media_id = pub_data.get("id", "")
                url = f"https://www.instagram.com/reel/{media_id}/" if media_id else ""
                logger.info("Instagram Reel published: %s", media_id)
                return PublishResult.ok(self.name, url=url, detail={"id": media_id})
        except Exception as exc:
            return PublishResult.failed(self.name, str(exc))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.youtube import find_latest_output_video

    load_dotenv()
    parser = argparse.ArgumentParser(description="Upload latest Reel to Instagram")
    parser.add_argument("video", nargs="?")
    args = parser.parse_args(argv)
    settings = load_settings()
    settings.publish_instagram = True  # type: ignore[attr-defined]
    settings.publish_enabled = True  # type: ignore[attr-defined]
    video = Path(args.video) if args.video else find_latest_output_video(settings.output_dir)
    if video is None:
        print("No video in output/", file=sys.stderr)
        return 2
    result = InstagramReelsPublisher().publish(
        video, PublishMeta(title=video.stem, caption=video.stem), settings
    )
    print(result.line())
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
