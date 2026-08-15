"""Upload vertical Reels to YouTube as Shorts (Data API v3 + OAuth2).

API key alone cannot upload — needs OAuth refresh token with scope
https://www.googleapis.com/auth/youtube.upload
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubeUploadError(RuntimeError):
    pass


def find_latest_output_video(output_dir: Path) -> Path | None:
    """Newest .mp4 under output/ (skips empty files)."""
    if not output_dir.exists():
        return None
    candidates = [
        p
        for p in output_dir.rglob("*.mp4")
        if p.is_file() and p.stat().st_size > 10_000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _caption_for_video(video: Path) -> tuple[str, str]:
    """Return (title, description) from sibling caption txt if present."""
    stem = video.stem
    for name in (f"{stem}.txt", f"{stem}_caption.txt", "telegram_post.txt"):
        path = video.with_name(name) if name.startswith(stem) else video.parent / name
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                first = text.splitlines()[0].strip()
                title = first[:90] if first else stem.replace("-", " ")
                return title, text
    title = stem.replace("-", " ").strip() or "Short"
    return title[:90], title


def ensure_shorts_markers(title: str, description: str) -> tuple[str, str]:
    """YouTube treats vertical ≤60s + #Shorts as a Short."""
    t = title.strip()
    d = description.strip()
    if "#shorts" not in t.lower() and "#Shorts" not in t:
        if len(t) <= 90:
            t = f"{t} #Shorts".strip()
        else:
            t = t[:90]
    if "#shorts" not in d.lower():
        d = f"{d}\n\n#Shorts".strip()
    return t[:100], d[:4900]


class YouTubeUploader:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        privacy: str = "public",
        category_id: str = "22",
    ) -> None:
        if not client_id or not client_secret or not refresh_token:
            raise YouTubeUploadError(
                "YouTube OAuth incomplete: set YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.privacy = privacy if privacy in ("public", "unlisted", "private") else "unlisted"
        self.category_id = category_id or "22"

    def access_token(self) -> str:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code >= 400:
            raise YouTubeUploadError(
                f"OAuth token refresh failed ({resp.status_code}): {resp.text[:400]}"
            )
        token = resp.json().get("access_token")
        if not token:
            raise YouTubeUploadError(f"No access_token in OAuth response: {resp.text[:300]}")
        return token

    def upload_short(
        self,
        video_path: Path,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if not video_path.exists():
            raise YouTubeUploadError(f"Video not found: {video_path}")

        auto_title, auto_desc = _caption_for_video(video_path)
        title, description = ensure_shorts_markers(
            title or auto_title,
            description or auto_desc,
        )
        tag_list = list(tags or [])
        if "Shorts" not in tag_list:
            tag_list.append("Shorts")

        token = self.access_token()
        size = video_path.stat().st_size
        mime = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tag_list[:15],
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": mime,
        }
        params = {
            "uploadType": "resumable",
            "part": "snippet,status",
        }

        with httpx.Client(timeout=120.0) as client:
            init = client.post(UPLOAD_URL, params=params, headers=headers, json=metadata)
            if init.status_code not in (200, 201):
                raise YouTubeUploadError(
                    f"YouTube resumable init failed ({init.status_code}): {init.text[:500]}"
                )
            upload_url = init.headers.get("Location")
            if not upload_url:
                raise YouTubeUploadError("YouTube did not return upload Location header")

            logger.info(
                "Uploading Short %s (%d bytes) as %s…",
                video_path.name,
                size,
                self.privacy,
            )
            # Stream file in one PUT (typical Reels < 50MB)
            with video_path.open("rb") as handle:
                put = client.put(
                    upload_url,
                    content=handle,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": mime,
                        "Content-Length": str(size),
                    },
                    timeout=600.0,
                )
            if put.status_code not in (200, 201):
                raise YouTubeUploadError(
                    f"YouTube upload failed ({put.status_code}): {put.text[:500]}"
                )
            data = put.json()
            video_id = data.get("id")
            if not video_id:
                raise YouTubeUploadError(f"No video id in upload response: {put.text[:300]}")
            url = f"https://youtube.com/shorts/{video_id}"
            logger.info("YouTube Short published: %s", url)
            return {"id": video_id, "url": url, "title": title, "privacy": self.privacy}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m src.publish.youtube [path.mp4]"""
    import argparse
    import sys

    from dotenv import load_dotenv

    from src.config import load_settings
    from src.publish.telegram import send_message

    load_dotenv()
    parser = argparse.ArgumentParser(description="Upload latest Reel as YouTube Short")
    parser.add_argument("video", nargs="?", help="Path to mp4 (default: newest in output/)")
    parser.add_argument("--title", default="")
    parser.add_argument("--privacy", default="")
    args = parser.parse_args(argv)

    settings = load_settings()
    video = Path(args.video) if args.video else find_latest_output_video(settings.output_dir)
    if video is None or not video.exists():
        print("No video found under output/ — render a Reel first", file=sys.stderr)
        return 2

    try:
        uploader = YouTubeUploader(
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            refresh_token=settings.youtube_refresh_token,
            privacy=args.privacy or settings.youtube_privacy,
            category_id=settings.youtube_category_id,
        )
        result = uploader.upload_short(video, title=args.title or None)
    except YouTubeUploadError as exc:
        print(f"UPLOAD_FAILED: {exc}", file=sys.stderr)
        if settings.telegram_notify and settings.telegram_bot_token:
            try:
                send_message(
                    settings.telegram_bot_token,
                    settings.telegram_owner_chat_id,
                    f"❌ YouTube Short upload failed\n{video.name}\n{exc}",
                )
            except Exception:
                pass
        return 1

    msg = (
        f"✅ YouTube Short\n{result['title']}\n"
        f"{result['url']}\nprivacy={result['privacy']}\nfile={video}"
    )
    print(msg)
    if settings.telegram_notify and settings.telegram_bot_token:
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
