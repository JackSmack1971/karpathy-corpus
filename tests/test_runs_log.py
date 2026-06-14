from __future__ import annotations

import importlib.util
import json
import tempfile
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


def test_main_writes_started_and_completed_run_records(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manifest_path = base_dir / "sources.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {"id": "source_ok", "kind": "url", "bucket": "papers", "url": "https://example.com/ok"},
                        {"id": "source_skip", "kind": "git", "bucket": "github", "url": "https://example.com/skip"},
                        {"id": "source_error", "kind": "copy_tree", "bucket": "github-blog", "source_dir": "sources/x"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        def fake_process_source(base_dir_arg, source, dry_run):
            if source["id"] == "source_ok":
                return {"status": "ok"}
            if source["id"] == "source_skip":
                return {"status": "skipped"}
            return {"status": "error", "error": "boom"}

        monkeypatch.setattr(MODULE, "process_source", fake_process_source)
        monkeypatch.setattr(
            MODULE.sys,
            "argv",
            [
                "ingest_karpathy_corpus.py",
                "--base-dir",
                str(base_dir),
                "--manifest",
                str(manifest_path),
            ],
        )

        exit_code = MODULE.main()

        assert exit_code == 0

        run_log_path = base_dir / "metadata" / "runs.jsonl"
        records = [json.loads(line) for line in run_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        assert len(records) == 2
        assert records[0]["event"] == "run_started"
        assert records[0]["source_count"] == 3
        assert "completed_at" not in records[0]
        assert records[1]["event"] == "run_completed"
        assert records[1]["run_id"] == records[0]["run_id"]
        assert records[1]["ok"] == 1
        assert records[1]["skipped"] == 1
        assert records[1]["error"] == 1
        assert "completed_at" in records[1]
