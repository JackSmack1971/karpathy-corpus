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


def test_copy_tree_skips_existing_output_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        source_dir = base_dir / "sources" / "github" / "karpathy.github.io" / "_posts"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "post.md").write_text("fresh content", encoding="utf-8")

        output_dir = base_dir / "raw" / "github-blog"
        output_dir.mkdir(parents=True, exist_ok=True)
        existing_file = output_dir / "post.md"
        existing_file.write_text("existing content", encoding="utf-8")

        result = MODULE.copy_tree(source_dir, output_dir, dry_run=False, force=False)

        assert result["status"] == "skipped"
        assert result["reason"] == "output already exists"
        assert existing_file.read_text(encoding="utf-8") == "existing content"


def test_copy_tree_forces_refresh_when_output_exists() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        source_dir = base_dir / "sources" / "github" / "karpathy.github.io" / "_posts"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "post.md").write_text("fresh content", encoding="utf-8")

        output_dir = base_dir / "raw" / "github-blog"
        output_dir.mkdir(parents=True, exist_ok=True)
        existing_file = output_dir / "post.md"
        existing_file.write_text("existing content", encoding="utf-8")

        result = MODULE.copy_tree(source_dir, output_dir, dry_run=False, force=True)

        assert result["status"] == "ok"
        assert result["files_copied"] == 1
        assert existing_file.read_text(encoding="utf-8") == "fresh content"


def test_main_skips_sources_with_unmet_depends_on(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manifest_path = base_dir / "sources.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {"id": "source_a", "kind": "url", "bucket": "papers", "url": "https://example.com/a", "output": "raw/a.md"},
                        {
                            "id": "source_b",
                            "kind": "copy_tree",
                            "bucket": "github-blog",
                            "depends_on": ["source_a"],
                            "source_dir": "sources/x",
                            "output": "raw/x",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        calls = []

        def fake_process_source(base_dir_arg, source, dry_run):
            calls.append(source["id"])
            if source["id"] == "source_a":
                return {"status": "error", "error": "boom"}
            return {"status": "ok"}

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
        assert calls == ["source_a"]

        skipped_log = base_dir / "metadata" / "skipped.jsonl"
        skipped_records = [json.loads(line) for line in skipped_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(record["id"] == "source_b" and record["reason"].startswith("unmet depends_on:") for record in skipped_records)
