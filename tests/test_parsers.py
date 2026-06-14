#!/usr/bin/env python3
r"""Local regression harness for the corpus normalizers.

Run this directly:

```powershell
python .\karpathy-corpus\tests\test_parsers.py
```
"""

from __future__ import annotations

import importlib.util
import argparse
import difflib
import json
from pathlib import Path
import sys

__test__ = False


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_karpathy_corpus.py"
FIXTURES = ROOT / "tests" / "fixtures"


def load_ingest_module():
    spec = importlib.util.spec_from_file_location("ingest_karpathy_corpus", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_text_diff(expected: str, actual: str, label: str, path: Path, max_lines: int = 12) -> str:
    diff_lines = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{path} (expected)",
            tofile=f"{path} (actual)",
            lineterm="",
        )
    )
    if not diff_lines:
        return f"{label} drift for {path}: no line diff available"
    preview = diff_lines[:max_lines]
    suffix = "" if len(diff_lines) <= max_lines else "\n... diff truncated ..."
    return f"{label} drift for {path}:\n" + "\n".join(preview) + suffix


def render_json_diff(expected, actual, label: str, path: Path, max_lines: int = 12) -> str:
    expected_text = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    actual_text = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return render_text_diff(expected_text, actual_text, label, path, max_lines=max_lines)


def test_html_fixtures(module, update_goldens: bool) -> None:
    cases = [
        ("html/karpathy_notes.html", "html/karpathy_notes.md"),
        ("html/clean_landing.html", "html/clean_landing.md"),
        ("html/heading_anchor.html", "html/heading_anchor.md"),
    ]
    for source_rel, golden_rel in cases:
        source = load_text(FIXTURES / source_rel)
        expected = load_text(FIXTURES / golden_rel)
        actual = module.html_to_markdown(source)
        if update_goldens:
            write_text(FIXTURES / golden_rel, actual)
            expected = actual
        if actual != expected:
            raise AssertionError(render_text_diff(expected, actual, "HTML normalization", FIXTURES / golden_rel))


def test_subtitle_fixtures(module, update_goldens: bool) -> None:
    cases = [
        ("subtitles/intro_walkthrough.srt", "subtitles/intro_walkthrough.json"),
        ("subtitles/guest_segment.vtt", "subtitles/guest_segment.json"),
    ]
    for source_rel, golden_rel in cases:
        source = load_text(FIXTURES / source_rel)
        expected = load_json(FIXTURES / golden_rel)
        if source_rel.endswith(".srt"):
            actual = module.parse_srt(source)
        else:
            actual = module.parse_vtt(source)
        if update_goldens:
            write_json(FIXTURES / golden_rel, actual)
            expected = actual
        if actual != expected:
            raise AssertionError(render_json_diff(expected, actual, "Subtitle parsing", FIXTURES / golden_rel))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run parser regression checks against checked-in fixtures.")
    parser.add_argument("--update-goldens", action="store_true", help="Rewrite golden outputs from the current normalizers")
    args = parser.parse_args()

    module = load_ingest_module()
    test_html_fixtures(module, args.update_goldens)
    test_subtitle_fixtures(module, args.update_goldens)
    if args.update_goldens:
        print("parser goldens updated")
    print("parser harness ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
