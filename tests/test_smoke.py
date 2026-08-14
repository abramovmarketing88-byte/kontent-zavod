"""Smoke tests for utility functions."""

from pathlib import Path
import tempfile

from src.assemble.captions import build_karaoke_ass
from src.models import WordTiming
from src.rewrite.fallback_llm import _parse_remake
from src.voice.elevenlabs import _alignment_to_words


def test_run_once_trigger_file() -> None:
    p = Path(__file__).resolve().parents[1] / "triggers" / "run-once.id"
    assert p.is_file()
    assert p.read_text(encoding="utf-8").strip()


def test_check_run_once_consumes_before_run() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts" / "check_run_once.sh").read_text(
        encoding="utf-8"
    )
    assert "Mark consumed immediately" in script or "echo \"$NEW_ID\" > \"$STATE_FILE\"" in script
    assert "flock" in script


def test_captions() -> None:
    words = [
        WordTiming(word="Привет", start=0.0, end=0.5),
        WordTiming(word="мир", start=0.5, end=1.0),
    ]
    with tempfile.TemporaryDirectory() as d:
        p = build_karaoke_ass(words, Path(d) / "t.ass", hook="Тест")
        content = p.read_text(encoding="utf-8-sig")
        assert "Привет" in content
        assert "Dialogue" in content


def test_parse_remake() -> None:
    raw = (
        '{"hook":"h","script":"s","shots":[{"keywords":["a"],"duration_sec":3}],'
        '"caption":"c","hashtags":["#t"],"title":"t"}'
    )
    r = _parse_remake(raw)
    assert r.title == "t"


def test_alignment() -> None:
    w = _alignment_to_words(
        {
            "characters": ["h", "i", " ", "!"],
            "character_start_times_seconds": [0, 0.1, 0.2, 0.3],
            "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4],
        }
    )
    assert [x.word for x in w] == ["hi", "!"]


if __name__ == "__main__":
    test_captions()
    test_parse_remake()
    test_alignment()
    print("All smoke tests passed")
