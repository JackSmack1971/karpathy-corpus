# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reproducible corpus builder for Andrej Karpathy's public content. `sources.manifest.json` declares every source; `scripts/ingest_karpathy_corpus.py` fetches, normalizes, and logs each one. The UI (`ui/`) is a static dashboard for browsing corpus state.

## Commands

**Run the ingest pipeline:**
```powershell
python .\scripts\ingest_karpathy_corpus.py
python .\scripts\ingest_karpathy_corpus.py --dry-run
python .\scripts\ingest_karpathy_corpus.py --base-dir <path> --manifest <path>
```

**Run parser regression tests (no pytest needed — standalone scripts):**
```powershell
python .\tests\test_parsers.py
python .\tests\test_parsers.py --update-goldens   # rewrite golden fixtures
```

**Run YouTube ingest tests (requires pytest for monkeypatching):**
```powershell
python -m pytest tests\test_youtube_ingest.py -v
```

**Serve the UI locally:**
```powershell
python -m http.server 8000   # run from repo root, then open http://localhost:8000/ui/
```

## Architecture

### Ingest pipeline (`scripts/ingest_karpathy_corpus.py`)

Single-file, stdlib-only pipeline. Four source `kind`s:
- `url` — downloads with `urllib`, HTML responses are auto-converted to Markdown via `MarkdownHTMLParser` and staged to `sources/html/`
- `git` — shallow-clones with `git`
- `copy_tree` — copies files from a cloned repo into `raw/`
- `youtube` — uses `yt-dlp` to fetch subtitles and info JSON per video, then normalizes to `karpathy.transcript.v1` schema

Optional tools (`git`, `yt-dlp`) are detected at runtime; missing tools produce `skipped` records instead of errors.

All run outcomes are appended to JSONL logs:
- `metadata/downloads.jsonl` — successful actions
- `metadata/skipped.jsonl` — skipped or errored actions
- `metadata/runs.jsonl` — per-run metadata

### Transcript schema (`karpathy.transcript.v1`)

JSON files in `raw/transcripts/` follow this schema: `schema`, `source_id`, `source_url`, `title`, `channel`, `language`, `duration`, `upload_date`, `captured_at`, `cue_count`, `cues[]` (each cue has `start`, `end`, `text` in seconds).

### Test approach

`tests/test_parsers.py` is a standalone harness (no pytest) that runs `html_to_markdown` and `parse_srt`/`parse_vtt` against golden fixtures in `tests/fixtures/`. Update goldens intentionally with `--update-goldens`.

`tests/test_youtube_ingest.py` uses pytest `monkeypatch` to mock `subprocess.run` and `shutil.which`; it tests retry/backoff, error-continuation across videos, stale-staging cleanup, and language inference.

## Invariants to preserve

- `sources.manifest.json` is the single source of truth; never hard-code source URLs in the script.
- `raw/` contains only derived/normalized content; `sources/` holds staged originals. Do not mix them.
- HTML normalization uses `MarkdownHTMLParser` (stdlib `html.parser` subclass) — no external HTML libraries.
- The transcript schema version (`karpathy.transcript.v1`) must not change without updating fixtures and existing outputs.
- The UI must remain static HTML/CSS/JS with no build step or framework.
- Prefer stdlib over new dependencies; the only optional external tools are `git` and `yt-dlp`.
