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


def test_http_failure_records_are_written_to_errors_jsonl(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manifest_path = base_dir / "sources.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "source_error",
                            "kind": "url",
                            "bucket": "papers",
                            "url": "https://example.com/missing.pdf",
                            "output": "raw/papers/missing.pdf",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        def fake_process_source(base_dir_arg, source, dry_run):
            return {
                "status": "error",
                "url": source["url"],
                "output": str(base_dir_arg / source["output"]),
                "error": "HTTP 403: Forbidden",
            }

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

        errors_log = base_dir / "metadata" / "errors.jsonl"
        skipped_log = base_dir / "metadata" / "skipped.jsonl"

        errors_records = [json.loads(line) for line in errors_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        skipped_records = [json.loads(line) for line in skipped_log.read_text(encoding="utf-8").splitlines() if line.strip()] if skipped_log.exists() else []

        assert any(record["id"] == "source_error" and record["status"] == "error" for record in errors_records)
        assert all(record["id"] != "source_error" for record in skipped_records)
