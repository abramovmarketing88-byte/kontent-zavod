"""HeyGen talking-head renderer — lip-sync avatar + karaoke captions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.assemble.captions import build_karaoke_ass
from src.assemble.ffmpeg import burn_subtitles
from src.config import Settings
from src.heygen.client import HeyGenClient, HeyGenError
from src.models import RemakeSpec, VoiceResult

logger = logging.getLogger(__name__)

CACHE_FILE = "heygen_asset.json"


class HeyGenRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = HeyGenClient(
            settings.heygen_api_key,
            engine=getattr(settings, "heygen_engine", "avatar_iii"),
        )

    def render(
        self,
        job_path: Path,
        remake: RemakeSpec,
        voice: VoiceResult,
        shot_clips: list[Path],
    ) -> Path:
        del shot_clips  # HeyGen uses avatar video instead of B-roll

        avatar_id = self.settings.heygen_avatar_id
        if not avatar_id:
            raise HeyGenError(
                "HEYGEN_AVATAR_ID not set — pick avatar in HeyGen UI or "
                "GET https://api.heygen.com/v2/avatars"
            )

        work = job_path / "render"
        work.mkdir(exist_ok=True)

        audio_path = Path(voice.audio_path)
        asset_id = self._audio_asset_id(job_path, audio_path)

        video_id = self.client.create_avatar_video(
            avatar_id=avatar_id,
            audio_asset_id=asset_id,
        )
        result = self.client.wait_for_video(video_id)
        video_url = result.get("video_url") or result.get("url")
        if not video_url:
            raise HeyGenError(f"No download URL in HeyGen response: {result}")

        raw_path = work / "heygen_raw.mp4"
        self.client.download_video(video_url, raw_path)

        ass_path = build_karaoke_ass(
            voice.words,
            work / "captions.ass",
            hook=remake.hook,
            hook_duration=2.0,
        )

        final_path = job_path / "final.mp4"
        burn_subtitles(raw_path, ass_path, final_path)
        logger.info("Rendered HeyGen video: %s", final_path)
        return final_path

    def _audio_asset_id(self, job_path: Path, audio_path: Path) -> str:
        cache_path = job_path / CACHE_FILE
        stat = audio_path.stat()
        cached: dict | None = None
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))

        if (
            cached
            and cached.get("path") == str(audio_path)
            and cached.get("size") == stat.st_size
            and cached.get("asset_id")
        ):
            return cached["asset_id"]

        asset_id = self.client.upload_audio(audio_path)
        cache_path.write_text(
            json.dumps(
                {
                    "path": str(audio_path),
                    "size": stat.st_size,
                    "asset_id": asset_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return asset_id
