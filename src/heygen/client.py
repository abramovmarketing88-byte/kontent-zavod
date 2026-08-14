"""HeyGen v3 API — upload audio, generate talking-head video, poll status."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.heygen.com"


class HeyGenError(RuntimeError):
    pass


class HeyGenClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise HeyGenError("HEYGEN_API_KEY not set")
        self.api_key = api_key
        self._headers = {"X-Api-Key": api_key}

    def upload_audio(self, audio_path: Path) -> str:
        with audio_path.open("rb") as handle:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{BASE_URL}/v3/assets",
                    headers=self._headers,
                    files={"file": (audio_path.name, handle, "audio/mpeg")},
                )
        self._raise_for_status(resp, "upload audio")
        data = resp.json().get("data") or {}
        asset_id = data.get("asset_id") or data.get("id")
        if not asset_id:
            raise HeyGenError(f"No asset_id in upload response: {resp.text[:300]}")
        logger.info("HeyGen audio asset: %s (%s)", asset_id, audio_path.name)
        return asset_id

    def create_avatar_video(
        self,
        *,
        avatar_id: str,
        audio_asset_id: str,
        aspect_ratio: str = "9:16",
        resolution: str = "1080p",
    ) -> str:
        payload = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "audio_asset_id": audio_asset_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{BASE_URL}/v3/videos",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
            )
        self._raise_for_status(resp, "create video")
        video_id = (resp.json().get("data") or {}).get("video_id")
        if not video_id:
            raise HeyGenError(f"No video_id in create response: {resp.text[:300]}")
        logger.info("HeyGen video queued: %s", video_id)
        return video_id

    def get_video(self, video_id: str) -> dict:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(
                f"{BASE_URL}/v3/videos/{video_id}",
                headers=self._headers,
            )
        self._raise_for_status(resp, "get video status")
        return resp.json().get("data") or {}

    def wait_for_video(
        self,
        video_id: str,
        *,
        poll_interval_sec: float = 15.0,
        timeout_sec: float = 1800.0,
    ) -> dict:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            data = self.get_video(video_id)
            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                raise HeyGenError(
                    f"HeyGen render failed: {data.get('error') or data}"
                )
            logger.info("HeyGen %s: %s", video_id, status or "pending")
            time.sleep(poll_interval_sec)
        raise HeyGenError(f"HeyGen render timed out after {timeout_sec:.0f}s")

    def download_video(self, url: str, dest: Path) -> Path:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        logger.info("HeyGen video saved: %s", dest)
        return dest

    @staticmethod
    def _raise_for_status(resp: httpx.Response, action: str) -> None:
        if resp.is_success:
            return
        try:
            err = resp.json().get("error") or {}
            message = err.get("message") or resp.text[:300]
            code = err.get("code") or resp.status_code
        except Exception:
            message = resp.text[:300]
            code = resp.status_code
        raise HeyGenError(f"HeyGen {action} failed ({code}): {message}")
