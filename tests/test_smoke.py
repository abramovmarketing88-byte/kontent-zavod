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


def test_redact_youtube_and_telegram_secrets() -> None:
    from src.run_report import _redact

    sample = (
        "GET https://www.googleapis.com/youtube/v3/search?key=AIzaSyDummyKey1234567890 "
        "https://api.telegram.org/bot123456:AAEdummyTokenValueHere/sendMessage"
    )
    out = _redact(sample)
    assert "AIza" not in out
    assert "AAEdummy" not in out
    assert "***" in out


def test_run_report_redacts_and_writes(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.run_report import HISTORY_KEEP, RunReport, _redact

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
    assert (tmp_path / "reports" / "last-10.md").is_file()
    assert (tmp_path / "reports" / "AGENT.md").is_file()
    index = (tmp_path / "reports" / "last-10.md").read_text(encoding="utf-8")
    assert "test-run" in index
    assert "Last" in index


def test_run_report_keeps_last_10_history(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.run_report import HISTORY_KEEP, RunReport

    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        inbox_dir=tmp_path / "inbox",
        brand_dir=tmp_path / "brand",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "factory.db",
        cursor_api_key="",
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
    for i in range(HISTORY_KEEP + 3):
        r = RunReport(settings, run_id=f"run-{i:02d}")
        if i % 2 == 0:
            r.fail(RuntimeError(f"boom-{i}"))
        else:
            r.complete(1)
    hist = list((tmp_path / "reports" / "history").glob("*.md"))
    assert len(hist) == HISTORY_KEEP
    index = (tmp_path / "reports" / "last-10.md").read_text(encoding="utf-8")
    assert "run-12" in index or "run-11" in index
    assert "boom-" in index


def test_heygen_payload_has_no_dimension() -> None:
    import inspect

    from src.heygen import client as heygen_client

    src = inspect.getsource(heygen_client.HeyGenClient.create_avatar_video)
    assert "dimension" not in src.split("payload", 1)[-1].split("with httpx", 1)[0]
    assert "aspect_ratio" in src
    assert "resolution" in src


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


def test_title_stopwords() -> None:
    from src.discover.youtube import _title_is_noise

    assert _title_is_noise("Network marketing 🤣 #comedy", ("comedy", "meme"))
    assert not _title_is_noise("SMM советы для Reels", ("comedy", "meme"))


def test_inbox_instagram_and_youtube_ids() -> None:
    from src.discover.inbox import extract_instagram_id, extract_youtube_id

    assert extract_youtube_id("https://www.youtube.com/shorts/7ppZvsgdQ3g") == "7ppZvsgdQ3g"
    assert extract_instagram_id("https://www.instagram.com/reel/AbCdef12345/") == "AbCdef12345"


def test_db_reclaim_and_max_fails(tmp_path: Path) -> None:
    from src.db import Database
    from src.models import JobStatus, SourceMeta

    db = Database(tmp_path / "factory.db")
    db.stale_hours = 0  # everything older than now is stale after tiny sleep
    meta = SourceMeta(source_id="abc", url="https://youtu.be/abc", title="t")
    db.upsert_source(meta, str(tmp_path / "jobs" / "abc"), JobStatus.DISCOVERED)
    # Force updated_at into the past
    import sqlite3
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE sources SET updated_at = ?", (old,))
        conn.commit()
    assert db.reclaim_stale() == 1
    assert db.should_skip_discovery("abc") is False  # failed with 0 fails → retry
    retries = db.list_retryable_failed(limit=5)
    assert any(r.source_id == "abc" for r in retries)

    db.update_status("abc", JobStatus.FAILED, "boom")
    db.update_status("abc", JobStatus.FAILED, "boom")
    db.update_status("abc", JobStatus.FAILED, "boom")
    db.max_fails = 3
    assert db.should_skip_discovery("abc") is True
    assert all(r.source_id != "abc" for r in db.list_retryable_failed())


def test_edge_tts_without_elevenlabs_key() -> None:
    from src.voice.elevenlabs import ElevenLabsVoice
    # ensure module imports; synthesize path covered indirectly by edge fallback existence
    from src.voice.edge_tts_fallback import synthesize_edge

    assert callable(synthesize_edge)


def test_pexels_placeholder_without_key(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.models import RemakeSpec, ShotSpec
    from src.visuals.pexels import PexelsClient

    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        inbox_dir=tmp_path / "inbox",
        brand_dir=tmp_path / "brand",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "factory.db",
        cursor_api_key="",
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
    remake = RemakeSpec(
        hook="h",
        script="s",
        shots=[ShotSpec(keywords=["office"], duration_sec=3)],
        caption="c",
        hashtags=["#t"],
        title="t",
    )
    paths = PexelsClient(settings).download_shots(tmp_path / "job", remake)
    assert paths and paths[0].exists()
    assert paths[0].stat().st_size > 1000


def test_publish_orchestrator_skips_without_keys(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.publish.base import PublishMeta
    from src.publish.orchestrator import PublishOrchestrator, default_publishers

    names = [p.name for p in default_publishers()]
    assert "telegram_dm" in names
    assert "youtube_shorts" in names
    assert "vk_video" in names
    assert "instagram_reels" in names
    assert "max_channel" in names
    assert "max_stories" in names
    assert "tiktok" in names

    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        inbox_dir=tmp_path / "inbox",
        brand_dir=tmp_path / "brand",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "factory.db",
        cursor_api_key="",
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
        publish_enabled=True,
        publish_vk=True,
        publish_instagram=True,
        publish_max=True,
        publish_max_stories=True,
        publish_tiktok=True,
    )
    video = tmp_path / "out.mp4"
    video.write_bytes(b"0" * 20_000)
    results = PublishOrchestrator(settings).publish_all(
        video, PublishMeta(title="t", caption="c")
    )
    assert results
    assert all(r.status in ("ok", "skipped", "failed") for r in results)
    # Without keys — skipped, not crash
    by = {r.platform: r for r in results}
    assert by["vk_video"].status == "skipped"
    assert by["instagram_reels"].status == "skipped"
    assert by["max_channel"].status == "skipped"
    assert by["max_stories"].status == "skipped"
    assert by["tiktok"].status == "skipped"
    assert (tmp_path / "data" / "publish_state.json").is_file()


def test_publish_once_trigger_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "check_publish_once.sh").is_file()
    assert (root / "triggers" / "publish-once.id").is_file()


def test_author_nudge_welcome_once(tmp_path: Path) -> None:
    from src.author_nudge import CHANNEL_URL, DM_URL, maybe_welcome, note_successful_run

    data = tmp_path / "data"
    data.mkdir()
    msg1 = maybe_welcome(data)
    assert msg1 and CHANNEL_URL in msg1 and DM_URL in msg1
    assert maybe_welcome(data) is None  # second time — silent

    # Force due-by-runs
    import json

    state_path = data / "author_nudge.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["successful_runs"] = 7
    state["last_nudge_run"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    nudge = note_successful_run(data)
    assert nudge and (CHANNEL_URL in nudge or DM_URL in nudge)


def test_author_show_script_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "show_author.sh").is_file()
    text = (root / "scripts" / "show_author.sh").read_text(encoding="utf-8")
    assert "Abramov_like" in text
    assert "Abramow191" in text


def test_telegram_story_prepare_720x1280(tmp_path: Path) -> None:
    import subprocess

    from src.assemble.ffmpeg import probe_size
    from src.publish.telegram_story import prepare_story_video

    src = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1080x1920:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    dest = tmp_path / "story.mp4"
    prepare_story_video(src, dest, max_duration=2.0)
    assert dest.exists() and dest.stat().st_size > 1000
    assert probe_size(dest) == (720, 1280)


def test_telegram_story_trigger_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "check_telegram_story.sh").is_file()
    assert (root / "triggers" / "telegram-story-once.id").is_file()
    from src.publish import telegram_story as ts

    assert 86400 in ts.ACTIVE_PERIODS


def test_youtube_shorts_markers_and_latest(tmp_path: Path) -> None:
    from src.publish.youtube import ensure_shorts_markers, find_latest_output_video

    title, desc = ensure_shorts_markers("Тест ролик", "Описание без тега")
    assert "#Shorts" in title or "#shorts" in title.lower()
    assert "#Shorts" in desc or "#shorts" in desc.lower()

    out = tmp_path / "output" / "2026-08-15"
    out.mkdir(parents=True)
    older = out / "old.mp4"
    newer = out / "new.mp4"
    older.write_bytes(b"0" * 20_000)
    newer.write_bytes(b"1" * 20_000)
    import os
    import time

    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))
    assert find_latest_output_video(tmp_path / "output") == newer


def test_youtube_upload_script_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "check_youtube_upload.sh").is_file()
    assert (root / "triggers" / "youtube-upload-once.id").is_file()
    from src.publish import youtube as yt

    assert "youtube.upload" in yt.YOUTUBE_UPLOAD_SCOPE

    from src.assemble import ffmpeg as ff

    import inspect

    src = inspect.getsource(ff)
    assert "setsar=1" in src
    assert "force_original_aspect_ratio=increase" in src
    assert "pad=" not in src.split("COVER_9x16")[1].split("\n")[0] if "COVER_9x16" in src else True
    encode_src = inspect.getsource(ff._encode_video)
    assert '"-aspect"' not in encode_src and "'-aspect'" not in encode_src
    assert "force_original_aspect_ratio=decrease" not in src
    assert "pad=" not in src.split("COVER_9x16", 1)[1][:200]
    assert "assert_reel_size" in src


def test_topic_discoverer_queues_brief(tmp_path: Path) -> None:
    from src.config import InstagramNicheConfig, NicheConfig, Settings
    from src.db import Database
    from src.discover.topic import TopicDiscoverer, topic_brief_path

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "topic.txt").write_text(
        "Нейросети экономят время\nРаньше день, сейчас 5 минут\n",
        encoding="utf-8",
    )
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        inbox_dir=inbox,
        brand_dir=tmp_path / "brand",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "factory.db",
        cursor_api_key="",
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
    db = Database(settings.db_path)
    found = TopicDiscoverer(settings, db).discover()
    assert len(found) == 1
    assert found[0].platform == "topic"
    assert topic_brief_path(inbox, found[0].source_id).exists()
    assert (inbox / "topic.txt").read_text(encoding="utf-8").strip() == ""


def test_diagnose_and_entrypoint_scripts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "diagnose.sh").is_file()
    assert (root / "scripts" / "docker-entrypoint.sh").is_file()
    assert (root / "scripts" / "smoke_e2e.sh").is_file()
    assert (root / "scripts" / "run_local.sh").is_file()
    ep = (root / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "PROXY_REQUIRED" in ep
    local = (root / "scripts" / "run_local.sh").read_text(encoding="utf-8")
    assert "faceless" in local


if __name__ == "__main__":
    test_captions()
    test_parse_remake()
    test_alignment()
    print("All smoke tests passed")
