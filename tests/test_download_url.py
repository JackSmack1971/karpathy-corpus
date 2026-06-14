from __future__ import annotations

import importlib.util
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


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/octet-stream") -> None:
        self._payload = payload
        self.headers = FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_download_url_skips_existing_output_without_force(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        output = base_dir / "raw" / "papers" / "paper.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"existing content")

        calls = {"count": 0}

        def fake_urlopen(*args, **kwargs):
            calls["count"] += 1
            raise AssertionError("urlopen should not be called when output already exists")

        monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)

        result = MODULE.download_url(
            base_dir,
            "https://example.com/paper.pdf",
            output,
            dry_run=False,
            source_id="paper_example",
            force=False,
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "output already exists"
        assert result["sha256"] == MODULE.sha256_file(output)
        assert result["bytes"] == output.stat().st_size
        assert calls["count"] == 0


def test_download_url_forces_refresh_even_when_output_exists(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        output = base_dir / "raw" / "papers" / "paper.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"existing content")

        calls = {"count": 0}

        def fake_urlopen(request):
            calls["count"] += 1
            return FakeResponse(b"refreshed content", content_type="application/pdf")

        monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)

        result = MODULE.download_url(
            base_dir,
            "https://example.com/paper.pdf",
            output,
            dry_run=False,
            source_id="paper_example",
            force=True,
        )

        assert result["status"] == "ok"
        assert result["content_type"] == "application/pdf"
        assert output.read_bytes() == b"refreshed content"
        assert calls["count"] == 1


def test_process_source_forwards_force_to_download_url(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        source = {
            "id": "paper_example",
            "kind": "url",
            "url": "https://example.com/paper.pdf",
            "output": "raw/papers/paper.pdf",
        }

        captured = {}

        def fake_download_url(base_dir_arg, url, output, dry_run, source_id, force=False):
            captured["base_dir"] = base_dir_arg
            captured["url"] = url
            captured["output"] = output
            captured["dry_run"] = dry_run
            captured["source_id"] = source_id
            captured["force"] = force
            return {"status": "ok", "url": url, "output": str(output)}

        monkeypatch.setattr(MODULE, "download_url", fake_download_url)

        result = MODULE.process_source(base_dir, source, dry_run=False, force=True)

        assert result["status"] == "ok"
        assert captured["base_dir"] == base_dir
        assert captured["url"] == source["url"]
        assert captured["output"] == base_dir / source["output"]
        assert captured["dry_run"] is False
        assert captured["source_id"] == source["id"]
        assert captured["force"] is True
