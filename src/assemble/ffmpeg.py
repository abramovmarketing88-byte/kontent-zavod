"""FFmpeg video assembly utilities."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.ffmpeg_bin import get_ffmpeg, probe_duration as _probe_duration

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920
FPS = 30


def probe_duration(path: Path) -> float:
    return _probe_duration(path)


def extract_audio_clip(src: Path, dest: Path, *, duration: float, start: float = 0.0) -> None:
    cmd = [
        get_ffmpeg(),
        "-y",
        "-ss",
        f"{start:.2f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.2f}",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.debug("Audio clip %.1fs -> %s", duration, dest.name)


def strip_audio(src: Path, dest: Path) -> None:
    cmd = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-an",
        "-c:v",
        "copy",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def normalize_talking_head(src: Path, dest: Path) -> None:
    """Scale/crop HeyGen output to true 9:16 with square pixels (no squash)."""
    # setsar=1 is mandatory: HeyGen often ships non-1 SAR which Telegram/players
    # then display as a flattened talking head with letterbox bars.
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={WIDTH}:{HEIGHT},"
        f"setsar=1,"
        f"fps={FPS}"
    )
    cmd = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-aspect",
        "9:16",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"normalize_talking_head failed: {result.stderr[-400:]}")
    logger.info("Normalized talking head -> %s", dest.name)


def normalize_clip(src: Path, dest: Path, duration: float) -> None:
    """Crop/scale to 9:16 (square pixels) and trim to duration with slight zoom."""
    # Avoid naked zoompan on anamorphic inputs — normalize geometry first.
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={WIDTH}:{HEIGHT},"
        f"setsar=1,"
        f"zoompan=z='min(1.0+0.0008*on,1.08)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={WIDTH}x{HEIGHT}:fps={FPS},"
        f"setsar=1"
    )
    cmd = [
        get_ffmpeg(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(src),
        "-t",
        f"{duration:.2f}",
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-aspect",
        "9:16",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback without zoompan if filter graph rejects the chain
        logger.warning("zoompan normalize failed, plain scale/crop: %s", result.stderr[-200:])
        vf_plain = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:force_divisible_by=2,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}"
        )
        cmd[cmd.index("-vf") + 1] = vf_plain
        subprocess.run(cmd, check=True, capture_output=True)
    logger.info("Normalized clip %s -> %s (%.1fs)", src.name, dest.name, duration)


def concat_clips(clips: list[Path], output: Path) -> None:
    """Concat clips with re-encode so mismatched SAR/timebase cannot squash the reel."""
    list_file = output.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clips),
        encoding="utf-8",
    )
    cmd = [
        get_ffmpeg(),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-vf",
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={FPS}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-aspect",
        "9:16",
        "-an",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"concat_clips failed: {result.stderr[-400:]}")
    logger.info("Concatenated %d clips -> %s", len(clips), output.name)


def mux_final(
    video: Path,
    audio: Path,
    subtitles: Path,
    output: Path,
) -> None:
    sub_path = subtitles.resolve().as_posix().replace("\\", "/").replace(":", "\\:")
    vf_sub = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"subtitles='{sub_path}'"
    )
    cmd_with_subs = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-vf",
        vf_sub,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-pix_fmt",
        "yuv420p",
        "-aspect",
        "9:16",
        str(output),
    ]
    result = subprocess.run(cmd_with_subs, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info("Final video: %s", output)
        return

    logger.warning("Subtitles burn failed, muxing without captions: %s", result.stderr[-200:])
    cmd_plain = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-vf",
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-pix_fmt",
        "yuv420p",
        "-aspect",
        "9:16",
        str(output),
    ]
    subprocess.run(cmd_plain, check=True, capture_output=True)
    logger.info("Final video (no captions): %s", output)


def burn_subtitles(video: Path, subtitles: Path, output: Path) -> None:
    """Burn ASS subtitles into video (audio track unchanged)."""
    sub_path = subtitles.resolve().as_posix().replace("\\", "/").replace(":", "\\:")
    vf_sub = f"subtitles='{sub_path}'"
    cmd = [
        get_ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-vf",
        vf_sub,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "copy",
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Subtitle burn failed: {result.stderr[-400:]}")
    logger.info("Video with captions: %s", output)
