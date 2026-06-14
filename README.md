# Karpathy Corpus Scaffold

This folder contains a reproducible starter layout for building a Karpathy corpus.

## What this gives you

- A stable directory layout for raw sources, cloned repos, transcripts, and metadata.
- A single manifest file that defines each source and how it should be acquired.
- One Python script that bootstraps the layout and ingests sources in a repeatable way.

## Layout

```text
karpathy-corpus/
  README.md
  sources.manifest.json
  metadata/
  raw/
    github-blog/
    bear-blog/
    medium/
    courses/
    github/
    transcripts/
      courses/
      youtube/
      talks/
      whisper/
    papers/
  sources/
    github/
    html/
    transcripts/
      cs231n-winter-2016/
      youtube/
      talks/
  scripts/
    ingest_karpathy_corpus.py
```

## Usage

Run from the repository root:

```powershell
python .\karpathy-corpus\scripts\ingest_karpathy_corpus.py
```

Useful flags:

- `--base-dir` to point at a different output directory.
- `--manifest` to use a different source manifest.
- `--dry-run` to show actions without downloading anything.

## Dependencies

The script uses only the Python standard library for URL downloads and metadata tracking.

Optional external tools:

- `git` for repository sources.
- `yt-dlp` for YouTube captions and playlist ingestion.
- `ffmpeg` is not required for the YouTube subtitle path; subtitles are fetched in native formats and normalized locally.

If an optional tool is missing, the script records the source as skipped and continues.

## Normalization

- HTML pages are downloaded to `sources/html/` first, then rendered to Markdown in `raw/`.
- YouTube captions are staged under `sources/transcripts/` and normalized into one JSON transcript per video in `raw/transcripts/`.
- The transcript schema is `karpathy.transcript.v1` with cue-level timing and text.

## UI

The `ui/` folder contains a simple static dashboard for the corpus scaffold.

Serve the folder locally so the page can fetch `sources.manifest.json`:

```powershell
cd .\karpathy-corpus
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/ui/
```

The dashboard shows the project intent, pipeline stages, bucket counts, and the tracked manifest entries.
