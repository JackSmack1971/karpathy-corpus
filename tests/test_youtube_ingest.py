from __future__ import annotations

import importlib.util
import json
import tempfile
import time as time_module
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_karpathy_corpus.py"


def load_ingest_module():
    spec = importlib.util.spec_from_file_location("ingest_karpathy_corpus", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_ingest_module()


class FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_command_construction() -> None:
    command = MODULE.build_youtube_command("yt-dlp", "https://www.youtube.com/watch?v=abc123", "tmp/%(id)s/%(id)s.%(ext)s")
    assert "--skip-download" in command
    assert "--write-subs" in command
    assert "--write-auto-subs" in command
    assert "--write-info-json" in command
    assert "--sub-langs" in command
    assert "en.*,en" in command
    assert "--ignore-errors" in command
    assert "--no-abort-on-error" in command
    assert "--retries" in command
    assert "--fragment-retries" in command
    assert "--convert-subs" not in command

    enumeration = MODULE.build_youtube_enumeration_command("yt-dlp", "https://www.youtube.com/@AndrejKarpathy/videos")
    assert "--flat-playlist" in enumeration
    assert "--dump-single-json" in enumeration
    assert "--ignore-errors" in enumeration
    assert "--convert-subs" not in enumeration


def test_validate_source_fields_contract() -> None:
    for kind, required_fields in MODULE.REQUIRED_FIELDS_BY_KIND.items():
        source = {"id": f"{kind}_source", "kind": kind}
        error = MODULE.validate_source_fields(source)

        assert error is not None
        assert error["status"] == "error"
        assert error["source_id"] == f"{kind}_source"
        assert error["kind"] == kind

        for field in required_fields:
            source[field] = f"present:{field}"

        assert MODULE.validate_source_fields(source) is None


def test_backoff_retries(monkeypatch) -> None:
    command = ["yt-dlp", "--version"]
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            return FakeCompletedProcess(1, stdout="", stderr="temporary failure")
        return FakeCompletedProcess(0, stdout="ok", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(time_module, "sleep", lambda _: None)
    result = MODULE.run_command_with_backoff(command, attempts=3, initial_delay=0.01)

    assert calls["count"] == 3
    assert result.returncode == 0
    assert result.stdout == "ok"


def test_process_youtube_source_continues_after_video_error(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        source = {
            "id": "example_youtube",
            "kind": "youtube",
            "url": "https://www.youtube.com/playlist?list=PL123",
            "staging_root": "sources/transcripts/youtube",
            "staging_template": "sources/transcripts/youtube/%(id)s/%(id)s.%(ext)s",
            "transcript_output": "raw/transcripts/youtube/%(id)s.json",
        }

        calls: list[list[str]] = []

        def fake_run(command, stdout=None, stderr=None, text=None):
            calls.append(command)
            if "--dump-single-json" in command:
                payload = {
                    "_type": "playlist",
                    "entries": [
                        {"id": "video_one", "url": "https://www.youtube.com/watch?v=video_one"},
                        {"id": "video_two", "url": "https://www.youtube.com/watch?v=video_two"},
                    ],
                }
                return FakeCompletedProcess(0, stdout=json.dumps(payload), stderr="")

            if any("video_one" in part for part in command):
                return FakeCompletedProcess(1, stdout="", stderr="HTTP Error 429: Too Many Requests")

            if any("video_two" in part for part in command):
                entry_dir = base_dir / "sources" / "transcripts" / "youtube" / "video_two"
                entry_dir.mkdir(parents=True, exist_ok=True)
                (entry_dir / "video_two.info.json").write_text(
                    json.dumps(
                        {
                            "id": "video_two",
                            "webpage_url": "https://www.youtube.com/watch?v=video_two",
                            "title": "Second video",
                            "language": "en",
                            "duration": 42,
                        }
                    ),
                    encoding="utf-8",
                )
                (entry_dir / "video_two.en.vtt").write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello there.\n",
                    encoding="utf-8",
                )
                return FakeCompletedProcess(0, stdout="", stderr="")

            return FakeCompletedProcess(0, stdout="", stderr="")

        monkeypatch.setattr(MODULE.shutil, "which", lambda name: "yt-dlp" if name == "yt-dlp" else None)
        monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
        result = MODULE.process_youtube_source(base_dir, source, dry_run=False)

        assert result["status"] == "ok"
        assert len(result["transcripts"]) == 2
        assert result["transcripts"][0]["status"] == "skipped"
        assert "429" in result["transcripts"][0]["reason"]
        assert result["transcripts"][1]["status"] == "ok"
        assert (base_dir / "raw" / "transcripts" / "youtube" / "video_two.json").exists()
        assert len(result["skipped_videos"]) == 1
        assert result["skipped_videos"][0]["video_id"] == "video_one"
        assert any("--dump-single-json" in command for command in calls)
        assert any(any("video_two" in part for part in command) for command in calls)


def test_normalize_transcript_infers_language_from_subtitle_name() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        subtitle_path = base_dir / "sources" / "transcripts" / "youtube" / "video_one" / "video_one.en.vtt"
        subtitle_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello there.\n",
            encoding="utf-8",
        )

        output = base_dir / "raw" / "transcripts" / "youtube" / "video_one.json"
        result = MODULE.normalize_transcript(
            {
                "id": "video_one",
                "webpage_url": "https://www.youtube.com/watch?v=video_one",
                "title": "First video",
                "duration": 42,
                "upload_date": "20240614",
            },
            subtitle_path,
            output,
            dry_run=False,
        )

        assert result["status"] == "ok"
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["language"] == "en"


def test_process_youtube_source_clears_stale_staging(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        source = {
            "id": "example_youtube",
            "kind": "youtube",
            "url": "https://www.youtube.com/playlist?list=PL123",
            "staging_root": "sources/transcripts/youtube",
            "staging_template": "sources/transcripts/youtube/%(id)s/%(id)s.%(ext)s",
            "transcript_output": "raw/transcripts/youtube/%(id)s.json",
        }
        entry_dir = base_dir / "sources" / "transcripts" / "youtube" / "video_one"
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "video_one.info.json").write_text("stale", encoding="utf-8")
        (entry_dir / "video_one.en.vtt").write_text("stale", encoding="utf-8")

        def fake_run(command, stdout=None, stderr=None, text=None):
            if "--dump-single-json" in command:
                payload = {
                    "_type": "playlist",
                    "entries": [{"id": "video_one", "url": "https://www.youtube.com/watch?v=video_one"}],
                }
                return FakeCompletedProcess(0, stdout=json.dumps(payload), stderr="")

            if any("video_one" in part for part in command):
                assert not (entry_dir / "video_one.info.json").exists()
                assert not (entry_dir / "video_one.en.vtt").exists()
                (entry_dir / "video_one.info.json").write_text(
                    json.dumps(
                        {
                            "id": "video_one",
                            "webpage_url": "https://www.youtube.com/watch?v=video_one",
                            "title": "Fresh video",
                            "duration": 42,
                        }
                    ),
                    encoding="utf-8",
                )
                (entry_dir / "video_one.en.vtt").write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello there.\n",
                    encoding="utf-8",
                )
                return FakeCompletedProcess(0, stdout="", stderr="")

            return FakeCompletedProcess(0, stdout="", stderr="")

        monkeypatch.setattr(MODULE.shutil, "which", lambda name: "yt-dlp" if name == "yt-dlp" else None)
        monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

        result = MODULE.process_youtube_source(base_dir, source, dry_run=False)

        assert result["status"] == "ok"
        assert result["transcripts"][0]["status"] == "ok"
        assert (base_dir / "raw" / "transcripts" / "youtube" / "video_one.json").exists()
