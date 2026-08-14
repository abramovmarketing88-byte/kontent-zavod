"""Resolve ffmpeg/ffprobe binary paths (system or bundled)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg or: pip install imageio-ffmpeg"
        ) from exc


@lru_cache(maxsize=1)
def get_ffprobe() -> str:
    env = os.getenv("FFPROBE_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    sibling = Path(get_ffmpeg()).with_name("ffprobe.exe")
    if sibling.exists():
        return str(sibling)
    return get_ffmpeg()


def probe_duration(path: Path) -> float:
    ffprobe = get_ffprobe()
    if Path(ffprobe).name.lower().startswith("ffprobe"):
        import json

        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))

    ffmpeg = get_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
    )
    match = re.search(r"Duration:\s(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return 0.0
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def ffmpeg_location_dir() -> str | None:
    path = Path(get_ffmpeg()).parent
    return str(path) if path.exists() else None
