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


def test_run_report_redacts_and_writes(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.run_report import RunReport, _redact

    assert "***" in _redact("api_key=sk-secret-value")

    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        inbox_dir=tmp_path / "inbox",
        brand_dir=tmp_path / "brand",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "factory.db",
        cursor_api_key="secret",
        elevenlabs_api_key="",
        elevenlabs_voice_id="",
        youtube_api_key="",
        pexels_api_key="",
        llm_api_key="",
        llm_base_url=None,
        llm_model="gpt-4o-mini",
        heygen_api_key="",
        heygen_avatar_id="",
        heygen_intro_sec=8.0,
        renderer="faceless",
        telegram_bot_token="",
        telegram_owner_chat_id="",
        telegram_notify=False,
        max_videos_per_run=1,
        schedule_hours=6,
        daily_at="09:00",
        schedule_tz="Europe/Moscow",
        whisper_model="base",
        transcribe_backend="faster_whisper",
        target_duration_min=30.0,
        target_duration_max=40.0,
        niche=NicheConfig(),
        instagram=InstagramNicheConfig(),
    )
    report = RunReport(settings, run_id="test-run")
    report.stage("discover")
    report.complete(0, empty=True)
    md = (tmp_path / "reports" / "last-run.md").read_text(encoding="utf-8")
    assert "test-run" in md
    assert "empty" in md
    assert "secret" not in md.lower() or "has_cursor_key" in md



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
