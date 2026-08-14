"""ASS subtitle generation with karaoke-style word highlighting."""

from __future__ import annotations

from pathlib import Path

from src.models import WordTiming


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_karaoke_ass(
    words: list[WordTiming],
    output_path: Path,
    hook: str = "",
    hook_duration: float = 2.0,
) -> Path:
    """Build ASS with yellow highlight on current word (Reels style)."""
    lines: list[str] = [
        "[Script Info]",
        "Title: Kontent Zavod",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Hook,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,5,40,40,480,1",
        "Style: Karaoke,Arial Black,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,200,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if hook:
        lines.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(hook_duration)},Hook,,0,0,0,,"
            f"{_escape_ass(hook)}"
        )

    # Group words into chunks of ~6 for readability
    chunk_size = 6
    for i in range(0, len(words), chunk_size):
        chunk = words[i : i + chunk_size]
        if not chunk:
            continue
        start = chunk[0].start
        end = chunk[-1].end

        parts: list[str] = []
        for w in chunk:
            dur_cs = max(int((w.end - w.start) * 100), 1)
            parts.append(f"{{\\k{dur_cs}}}{_escape_ass(w.word)}")

        text = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end + 0.3)},Karaoke,,0,0,0,,{text}"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return output_path
