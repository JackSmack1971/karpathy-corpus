# AGENTS.md

Read this first when working in the repository.

## Project Intent

This repository builds a reproducible Karpathy corpus from a manifest of source URLs and local assets. The main job is to ingest, normalize, and track sources without losing traceability back to the original material.

## Repo Map

- `README.md` - high-level project description and usage.
- `sources.manifest.json` - source-of-truth manifest for what should be acquired.
- `scripts/ingest_karpathy_corpus.py` - bootstrap and ingestion pipeline.
- `metadata/` - run logs and skip records.
- `raw/` - normalized outputs generated from source material.
- `sources/` - staged source material and intermediate artifacts.
- `tests/` - regression harnesses and fixtures for parser and ingest behavior.
- `ui/` - static dashboard for browsing the corpus scaffold.

## Working Rules

1. Read `README.md` and the relevant script or test files before editing anything.
2. Treat `scripts/ingest_karpathy_corpus.py` as the behavioral reference for layout, downloads, normalization, and metadata writes.
3. Preserve reproducibility. Do not silently change output formats, directory layout, or metadata schemas.
4. Keep raw inputs and normalized outputs distinct. Do not overwrite source material when a derived artifact is intended.
5. When changing parsers or transcript normalization, update the matching fixtures in `tests/fixtures/` and rerun the relevant tests.
6. Prefer the standard library and the existing script patterns over introducing new dependencies.

## Invariants

- Completed actions are recorded in `metadata/downloads.jsonl`.
- Skipped actions are recorded in `metadata/skipped.jsonl`.
- HTML inputs are normalized to markdown.
- Subtitle inputs are normalized to the repository transcript schema.
- The static UI should remain lightweight and file-serving friendly.

## Edit Guidance

- For ingestion changes, inspect `scripts/ingest_karpathy_corpus.py` first.
- For parser regressions, use `tests/test_parsers.py` and the fixture corpus under `tests/fixtures/`.
- For YouTube ingest behavior, use `tests/test_youtube_ingest.py`.
- For UI changes, keep the existing static structure simple and avoid adding framework overhead.

## Validation

- Run the smallest relevant test scope for the change.
- If you touch normalization logic, verify golden outputs intentionally rather than by accident.
- If you touch manifest-driven behavior, confirm the metadata logs still make sense.
