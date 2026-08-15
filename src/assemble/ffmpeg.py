"""FFmpeg video assembly utilities — always emit true 1080x1920 square-pixel Reels."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.ffmpeg_bin import get_ffmpeg, get_ffprobe, probe_duration as _probe_duration

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Cover-fit into 9:16, then force square pixels. Never pad (pad = black bars + squash in TG).
COVER_9x16 = (
    f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:force_divisible_by=2,"
    f"crop={WIDTH}:{HEIGHT},"
    f"setsar=1"
)


def probe_duration(path: Path) -> float:
    return _probe_duration(path)


def probe_size(path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    ffprobe = get_ffprobe()
    if Path(ffprobe).name.lower().startswith("ffprobe"):
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        raw = (result.stdout or "").strip().splitlines()[0]
        w_s, h_s = raw.split("x")
        return int(w_s), int(h_s)

    # Fallback: parse ffmpeg -i stderr
    result = subprocess.run(
        [get_ffmpeg(), "-i", str(path)],
        capture_output=True,
        text=True,
    )
    import re

    match = re.search(r"(\d{2,5})x(\d{2,5})", result.stderr)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def assert_reel_size(path: Path, *, label: str) -> None:
    w, h = probe_size(path)
    if (w, h) != (WIDTH, HEIGHT):
        raise RuntimeError(
            f"{label} has size {w}x{h}, expected {WIDTH}x{HEIGHT}: {path}"
        )
    logger.info("%s OK size %dx%d", label, w, h)


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


def _encode_video(src: Path, dest: Path, vf: str, *, duration: float | None = None) -> None:
    cmd = [
        get_ffmpeg(),
        "-y",
    ]
    if duration is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(src), "-t", f"{duration:.2f}"])
    else:
        cmd.extend(["-i", str(src)])
    cmd.extend(
        [
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            # Do NOT pass -aspect: it overrides pixel geometry and Telegram shows squash.
            str(dest),
        ]
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {result.stderr[-500:]}")


def normalize_talking_head(src: Path, dest: Path) -> None:
    """Cover-fit HeyGen output to exact 1080x1920 square pixels."""
    w, h = probe_size(src)
    logger.info("HeyGen raw size before normalize: %dx%d (%s)", w, h, src.name)
    _encode_video(src, dest, f"{COVER_9x16},fps={FPS}")
    assert_reel_size(dest, label="talking_head")


def normalize_clip(src: Path, dest: Path, duration: float) -> None:
    """Cover-fit B-roll to exact 1080x1920 (no zoompan — it breaks SAR)."""
    _encode_video(src, dest, f"{COVER_9x16},fps={FPS}", duration=duration)
    assert_reel_size(dest, label=dest.name)


def concat_clips(clips: list[Path], output: Path) -> None:
    """Concat already-normalized 1080x1920 clips, then force geometry again."""
    for clip in clips:
        assert_reel_size(clip, label=clip.name)

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
        f"{COVER_9x16},fps={FPS}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"concat_clips failed: {result.stderr[-400:]}")
    assert_reel_size(output, label="concat")
    logger.info("Concatenated %d clips -> %s", len(clips), output.name)


def mux_final(
    video: Path,
    audio: Path,
    subtitles: Path,
    output: Path,
) -> None:
    assert_reel_size(video, label="pre-mux video")
    sub_path = subtitles.resolve().as_posix().replace("\\", "/").replace(":", "\\:")
    vf_sub = f"{COVER_9x16},subtitles='{sub_path}'"
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
        str(output),
    ]
    result = subprocess.run(cmd_with_subs, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("Subtitles burn failed, muxing without captions: %s", result.stderr[-200:])
        cmd_plain = [
            get_ffmpeg(),
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-vf",
            COVER_9x16,
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
            str(output),
        ]
        subprocess.run(cmd_plain, check=True, capture_output=True)
        logger.info("Final video (no captions): %s", output)
    else:
        logger.info("Final video: %s", output)
    assert_reel_size(output, label="final")


def burn_subtitles(video: Path, subtitles: Path, output: Path) -> None:
    """Burn ASS subtitles into video (audio track unchanged)."""
    sub_path = subtitles.resolve().as_posix().replace("\\", "/").replace(":", "\\:")
    vf_sub = f"{COVER_9x16},subtitles='{sub_path}'"
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
    assert_reel_size(output, label="burn_subtitles")
    logger.info("Video with captions: %s", output)
