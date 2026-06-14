#!/usr/bin/env python3
"""Bootstrap and ingest a Karpathy corpus from a manifest.

The script is intentionally conservative:
- plain URLs are downloaded with the Python standard library
- git repos are cloned only when `git` is available
- YouTube sources are fetched with `yt-dlp` only when available

Each completed action is recorded in `metadata/downloads.jsonl`.
Skipped actions are recorded in `metadata/skipped.jsonl`.
"""

from __future__ import annotations

import argparse
import html
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


LAYOUT_DIRS = [
    "metadata",
    "raw/github-blog",
    "raw/bear-blog",
    "raw/medium",
    "raw/courses",
    "raw/github",
    "raw/transcripts/courses",
    "raw/transcripts/youtube",
    "raw/transcripts/talks",
    "raw/transcripts/whisper",
    "raw/papers",
    "sources/github",
    "sources/html",
    "sources/transcripts/cs231n-winter-2016",
    "sources/transcripts/youtube",
    "sources/transcripts/talks",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_layout(base_dir: Path) -> None:
    for rel in LAYOUT_DIRS:
        (base_dir / rel).mkdir(parents=True, exist_ok=True)


def confine_to_base(base_dir: Path, candidate: Path, label: str) -> None:
    base_resolved = base_dir.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal detected for {label!r} — resolves outside base_dir: {candidate!r}"
        ) from exc


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


class MarkdownHTMLParser(HTMLParser):
    block_tags = {
        "article",
        "aside",
        "blockquote",
        "div",
        "footer",
        "header",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "tbody",
        "thead",
        "tfoot",
        "tr",
        "ul",
        "ol",
        "li",
        "pre",
        "figure",
    }
    heading_tags = {f"h{i}" for i in range(1, 7)}
    break_tags = {"br", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.current_line_has_content = False
        self.link_stack: list[dict] = []
        self.pre_mode = False
        self.skip_depth = 0
        self.list_stack: list[str] = []
        self.pending_heading_prefix = ""

    def _append_fragment(self, fragment: str) -> None:
        if fragment:
            self.current.append(fragment)
            self.current_line_has_content = True

    def _emit_line(self, blank: bool = False) -> None:
        line = "".join(self.current).strip()
        if line:
            self.lines.append(line)
        elif blank and self.lines and self.lines[-1] != "":
            self.lines.append("")
        self.current = []
        self.current_line_has_content = False
        self.pending_heading_prefix = ""

    def _ensure_blank_line(self) -> None:
        self._emit_line()
        if not self.lines or self.lines[-1] != "":
            self.lines.append("")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value for name, value in attrs}
        if tag in {"script", "style", "noscript", "head"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self.heading_tags:
            self._ensure_blank_line()
            self.pending_heading_prefix = "#" * int(tag[1]) + " "
            return
        if tag in self.block_tags:
            if self.current_line_has_content:
                self._emit_line()
                self.lines.append("")
            elif not self.lines or self.lines[-1] != "":
                self.lines.append("")
        if tag == "li":
            self._emit_line()
            self._append_fragment("- ")
        elif tag == "br":
            self._emit_line()
        elif tag == "pre":
            self._ensure_blank_line()
            self.lines.append("```")
            self.pre_mode = True
        elif tag == "a":
            self.link_stack.append({"href": attrs_dict.get("href"), "text": []})

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "head"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "a" and self.link_stack:
            link = self.link_stack.pop()
            text = normalize_whitespace("".join(link["text"]))
            href = link.get("href")
            if href and text:
                self._append_fragment(f"[{text}]({href})")
            elif text:
                self._append_fragment(text)
            elif href:
                self._append_fragment(href)
            return
        if tag == "pre" and self.pre_mode:
            self._emit_line()
            self.lines.append("```")
            self.pre_mode = False
            self.lines.append("")
            return
        if tag in self.heading_tags or tag in self.block_tags:
            self._emit_line(blank=True)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = html.unescape(data)
        if not text.strip():
            if self.pre_mode:
                self._append_fragment(text)
            return
        if self.pending_heading_prefix:
            self._append_fragment(self.pending_heading_prefix)
            self.pending_heading_prefix = ""
        if self.link_stack:
            self.link_stack[-1]["text"].append(text)
            return
        if self.pre_mode:
            self._append_fragment(text)
        else:
            self._append_fragment(normalize_whitespace(text) + " ")

    def get_markdown(self) -> str:
        self._emit_line()
        lines = [line.rstrip() for line in self.lines]
        cleaned: list[str] = []
        previous_blank = True
        for line in lines:
            if not line:
                if not previous_blank:
                    cleaned.append("")
                previous_blank = True
                continue
            cleaned.append(line)
            previous_blank = False
        return "\n".join(cleaned).strip() + "\n"


def html_to_markdown(source_html: str) -> str:
    parser = MarkdownHTMLParser()
    parser.feed(source_html)
    parser.close()
    return parser.get_markdown()


TIMESTAMP_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$")
SRT_CUE_RE = re.compile(
    r"^\s*(?:(\d+)\s+)?(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,.]\d{3}).*$"
)
VTT_CUE_RE = re.compile(
    r"^\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,.]\d{3}).*$"
)


def timestamp_to_seconds(timestamp: str) -> float:
    match = TIMESTAMP_RE.match(timestamp.replace(",", "."))
    if not match:
        raise ValueError(f"invalid timestamp: {timestamp}")
    hours, minutes, seconds, millis = match.groups()
    return (int(hours) * 3600) + (int(minutes) * 60) + int(seconds) + (int(millis) / 1000.0)


def clean_caption_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_srt(text: str) -> list[dict]:
    cues: list[dict] = []
    for block in re.split(r"\r?\n\r?\n+", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timestamp_line_index = 0
        if not SRT_CUE_RE.match(lines[0]):
            if len(lines) < 3:
                continue
            timestamp_line_index = 1
        match = SRT_CUE_RE.match(lines[timestamp_line_index])
        if not match:
            continue
        _, start, end = match.groups()
        cue_text = clean_caption_text(" ".join(lines[timestamp_line_index + 1 :]))
        if cue_text:
            cues.append(
                {
                    "start": timestamp_to_seconds(start),
                    "end": timestamp_to_seconds(end),
                    "text": cue_text,
                }
            )
    return cues


def parse_vtt(text: str) -> list[dict]:
    cues: list[dict] = []
    lines = [line.rstrip("\n\r") for line in text.splitlines()]
    index = 0
    if lines and lines[0].startswith("WEBVTT"):
        index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    block: list[str] = []
    for line in lines[index:]:
        if not line.strip():
            if block:
                cues.extend(parse_vtt_block(block))
                block = []
            continue
        block.append(line)
    if block:
        cues.extend(parse_vtt_block(block))
    return cues


def parse_vtt_block(block: list[str]) -> list[dict]:
    if not block:
        return []
    if block[0].strip() and not VTT_CUE_RE.match(block[0].strip()):
        if len(block) < 2:
            return []
        block = block[1:]
    if not block:
        return []
    match = VTT_CUE_RE.match(block[0].strip())
    if not match:
        return []
    start, end = match.groups()
    cue_text = clean_caption_text(" ".join(block[1:]))
    if not cue_text:
        return []
    return [
        {
            "start": timestamp_to_seconds(start),
            "end": timestamp_to_seconds(end),
            "text": cue_text,
        }
    ]


def extract_youtube_metadata(info_path: Path) -> dict:
    with info_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def locate_subtitle_file(video_dir: Path) -> Path | None:
    candidates = sorted(
        [
            path
            for path in video_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".srt", ".vtt"}
        ],
        key=lambda path: (0 if ".en." in path.name else 1, path.name),
    )
    return candidates[0] if candidates else None


def infer_subtitle_language(info: dict, subtitle_path: Path) -> str:
    language = info.get("language")
    if isinstance(language, str) and language.strip():
        return language

    source_id = info.get("id")
    if isinstance(source_id, str) and source_id:
        stem = subtitle_path.stem
        prefix = f"{source_id}."
        if stem.startswith(prefix):
            inferred = stem[len(prefix) :].strip()
            if inferred:
                return inferred

    return "und"


def run_command_with_backoff(
    command: list[str],
    *,
    attempts: int = 3,
    initial_delay: float = 1.0,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    delay = initial_delay
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        result = subprocess.run(command, stdout=stdout, stderr=stderr, text=text)
        last_result = result
        if result.returncode == 0 or attempt == attempts:
            return result
        if delay > 0:
            import time

            time.sleep(delay)
            delay *= 2
    assert last_result is not None
    return last_result


def normalize_transcript(info: dict, subtitle_path: Path, output: Path, dry_run: bool) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "subtitle_path": str(subtitle_path),
            "output": str(output),
        }

    content = subtitle_path.read_text(encoding="utf-8", errors="replace")
    if subtitle_path.suffix.lower() == ".srt":
        cues = parse_srt(content)
    else:
        cues = parse_vtt(content)

    if not cues:
        return {
            "status": "skipped",
            "subtitle_path": str(subtitle_path),
            "output": str(output),
            "reason": "no subtitle cues found",
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "karpathy.transcript.v1",
        "source_id": info.get("id"),
        "source_url": info.get("webpage_url") or info.get("original_url"),
        "title": info.get("title"),
        "channel": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "language": infer_subtitle_language(info, subtitle_path),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "captured_at": utc_now(),
        "subtitle_path": str(subtitle_path),
        "cue_count": len(cues),
        "cues": cues,
    }
    with output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    return {
        "status": "ok",
        "subtitle_path": str(subtitle_path),
        "output": str(output),
        "cue_count": len(cues),
        "sha256": sha256_file(output),
        "bytes": output.stat().st_size,
    }


def download_url(base_dir: Path, url: str, output: Path, dry_run: bool, source_id: str) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "url": url,
            "output": str(output),
        }

    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request) as response:
            content = response.read()
            content_type = response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        return {
            "status": "error",
            "url": url,
            "output": str(output),
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {
            "status": "error",
            "url": url,
            "output": str(output),
            "error": str(exc.reason),
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".md", ".markdown"} or content_type == "text/html":
        staging = base_dir / "sources" / "html" / f"{source_id}.html"
        staging.parent.mkdir(parents=True, exist_ok=True)
        with staging.open("wb") as fh:
            fh.write(content)
        markdown = html_to_markdown(content.decode("utf-8", errors="replace"))
        with output.open("w", encoding="utf-8") as fh:
            fh.write(markdown)
        return {
            "status": "ok",
            "url": url,
            "output": str(output),
            "staging_html": str(staging),
            "normalized": "markdown",
            "sha256": sha256_file(output),
            "bytes": output.stat().st_size,
            "content_type": content_type,
        }

    with output.open("wb") as fh:
        fh.write(content)
    return {
        "status": "ok",
        "url": url,
        "output": str(output),
        "sha256": sha256_file(output),
        "bytes": output.stat().st_size,
        "content_type": content_type,
    }


def clone_git_repo(url: str, output: Path, dry_run: bool) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "url": url,
            "output": str(output),
        }

    if output.exists():
        return {
            "status": "skipped",
            "url": url,
            "output": str(output),
            "reason": "destination already exists",
        }

    git = shutil.which("git")
    if not git:
        return {
            "status": "skipped",
            "url": url,
            "output": str(output),
            "reason": "git not available",
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [git, "clone", "--depth", "1", url, str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "url": url,
            "output": str(output),
            "error": result.stderr.strip() or result.stdout.strip(),
        }

    return {
        "status": "ok",
        "url": url,
        "output": str(output),
    }


def copy_tree(source_dir: Path, output_dir: Path, dry_run: bool) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "source_dir": str(source_dir),
            "output": str(output_dir),
        }

    if not source_dir.exists():
        return {
            "status": "skipped",
            "source_dir": str(source_dir),
            "output": str(output_dir),
            "reason": "source directory does not exist",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1

    return {
        "status": "ok",
        "source_dir": str(source_dir),
        "output": str(output_dir),
        "files_copied": copied,
    }


def build_youtube_command(ytdlp: str, url: str, staging_template: str) -> list[str]:
    return [
        ytdlp,
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--write-info-json",
        "--sub-langs",
        "en.*,en",
        "--ignore-errors",
        "--no-abort-on-error",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "-o",
        staging_template,
        url,
    ]


def build_youtube_enumeration_command(ytdlp: str, url: str) -> list[str]:
    return [
        ytdlp,
        "--flat-playlist",
        "--skip-download",
        "--dump-single-json",
        "--ignore-errors",
        "--no-abort-on-error",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        url,
    ]


def parse_youtube_entries(payload: dict) -> list[dict]:
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [payload]


def youtube_entry_url(entry: dict) -> str | None:
    for key in ("webpage_url", "url", "original_url"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            if value.startswith("http://") or value.startswith("https://"):
                return value
            if key == "url" and entry.get("id"):
                return f"https://www.youtube.com/watch?v={entry['id']}"
    entry_id = entry.get("id")
    if isinstance(entry_id, str) and entry_id:
        return f"https://www.youtube.com/watch?v={entry_id}"
    return None


def fetch_youtube(url: str, staging_template: str, dry_run: bool) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "url": url,
            "staging_template": staging_template,
        }

    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return {
            "status": "skipped",
            "url": url,
            "staging_template": staging_template,
            "reason": "yt-dlp not available",
        }

    command = build_youtube_command(ytdlp, url, staging_template)
    result = run_command_with_backoff(command)
    if result.returncode != 0:
        return {
            "status": "error",
            "url": url,
            "staging_template": staging_template,
            "error": result.stderr.strip() or result.stdout.strip(),
        }

    return {
        "status": "ok",
        "url": url,
        "staging_template": staging_template,
    }


def enumerate_youtube_entries(url: str, dry_run: bool) -> dict:
    if dry_run:
        return {
            "status": "dry-run",
            "url": url,
        }

    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return {
            "status": "skipped",
            "url": url,
            "reason": "yt-dlp not available",
        }

    command = build_youtube_enumeration_command(ytdlp, url)
    result = run_command_with_backoff(command)
    if result.returncode != 0:
        return {
            "status": "error",
            "url": url,
            "error": result.stderr.strip() or result.stdout.strip(),
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "url": url,
            "error": f"invalid yt-dlp output: {exc}",
        }

    return {
        "status": "ok",
        "url": url,
        "entries": parse_youtube_entries(payload),
    }


def process_youtube_source(base_dir: Path, source: dict, dry_run: bool) -> dict:
    url = source.get("url")
    staging_template = source.get("staging_template")
    staging_root = source.get("staging_root")
    transcript_output = source.get("transcript_output")
    if staging_template is None:
        raise ValueError(f"source {source['id']} is missing staging_template")
    if staging_root is None:
        raise ValueError(f"source {source['id']} is missing staging_root")
    if transcript_output is None:
        raise ValueError(f"source {source['id']} is missing transcript_output")

    enumerate_result = enumerate_youtube_entries(url, dry_run)
    if enumerate_result.get("status") != "ok":
        return enumerate_result

    staging_root_path = base_dir / staging_root
    confine_to_base(base_dir, staging_root_path, "staging_root")

    transcript_results: list[dict] = []
    skipped_videos: list[dict] = []
    for entry in enumerate_result.get("entries", []):
        video_id = entry.get("id")
        video_url = youtube_entry_url(entry)
        safe_video_id = re.sub(r"[^\w\-]", "_", str(video_id or entry.get("display_id") or "unknown"))
        entry_dir = staging_root_path / safe_video_id
        confine_to_base(base_dir, entry_dir, "staging entry dir")
        if entry_dir.exists():
            if entry_dir.is_dir():
                shutil.rmtree(entry_dir)
            else:
                entry_dir.unlink()
        entry_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(entry_dir / f"{safe_video_id}.%(ext)s")

        if not video_url:
            result = {
                "status": "skipped",
                "source_url": url,
                "video_id": video_id,
                "reason": "could not determine video url",
            }
            transcript_results.append(result)
            skipped_videos.append(result)
            continue

        fetch_result = fetch_youtube(video_url, output_template, dry_run)
        if fetch_result.get("status") != "ok":
            result = {
                "status": "skipped",
                "source_url": url,
                "video_id": video_id,
                "video_url": video_url,
                "reason": fetch_result.get("error") or fetch_result.get("reason") or "fetch failed",
            }
            transcript_results.append(result)
            skipped_videos.append(result)
            continue

        info_path = entry_dir / f"{video_id or entry_dir.name}.info.json"
        if not info_path.exists():
            result = {
                "status": "skipped",
                "source_url": url,
                "video_id": video_id,
                "video_url": video_url,
                "reason": "no info.json file found",
            }
            transcript_results.append(result)
            skipped_videos.append(result)
            continue

        info = extract_youtube_metadata(info_path)
        subtitle_path = locate_subtitle_file(entry_dir)
        if subtitle_path is None:
            result = {
                "status": "skipped",
                "source_url": url,
                "video_id": video_id,
                "video_url": video_url,
                "reason": "no subtitle file found",
            }
            transcript_results.append(result)
            skipped_videos.append(result)
            continue

        safe_transcript_id = re.sub(
            r"[^\w\-]",
            "_",
            str(info.get("id", video_id or entry_dir.name)),
        )
        output_path = base_dir / transcript_output.replace("%(id)s", safe_transcript_id)
        confine_to_base(base_dir, output_path, "transcript_output")
        transcript_results.append(normalize_transcript(info, subtitle_path, output_path, dry_run))

    ok_count = sum(1 for transcript in transcript_results if transcript.get("status") == "ok")
    if ok_count == 0 and transcript_results:
        return {
            "status": "error",
            "url": url,
            "staging_template": staging_template,
            "staging_root": str(base_dir / staging_root),
            "error": "no transcripts produced",
            "transcripts": transcript_results,
            "skipped_videos": skipped_videos,
        }

    return {
        "status": "ok",
        "url": url,
        "staging_template": staging_template,
        "staging_root": str(base_dir / staging_root),
        "transcripts": transcript_results,
        "skipped_videos": skipped_videos,
    }


def process_source(base_dir: Path, source: dict, dry_run: bool) -> dict:
    kind = source["kind"]
    url = source.get("url")
    output = source.get("output")

    if kind == "url":
        if output is None:
            raise ValueError(f"source {source['id']} is missing output")
        output_path = base_dir / output
        confine_to_base(base_dir, output_path, "output")
        return download_url(base_dir, url, output_path, dry_run, source["id"])
    if kind == "git":
        if output is None:
            raise ValueError(f"source {source['id']} is missing output")
        output_path = base_dir / output
        confine_to_base(base_dir, output_path, "output")
        return clone_git_repo(url, output_path, dry_run)
    if kind == "copy_tree":
        source_dir = source.get("source_dir")
        if source_dir is None:
            raise ValueError(f"source {source['id']} is missing source_dir")
        if output is None:
            raise ValueError(f"source {source['id']} is missing output")
        source_path = base_dir / source_dir
        output_path = base_dir / output
        confine_to_base(base_dir, source_path, "source_dir")
        confine_to_base(base_dir, output_path, "output")
        return copy_tree(source_path, output_path, dry_run)
    if kind == "youtube":
        return process_youtube_source(base_dir, source, dry_run)

    return {
        "status": "skipped",
        "url": url,
        "output": output,
        "reason": f"unknown kind: {kind}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a Karpathy corpus from a manifest.")
    parser.add_argument(
        "--base-dir",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Corpus root directory (default: parent of this script)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        type=Path,
        help="Path to the source manifest (default: <base-dir>/sources.manifest.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without downloading")
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    manifest_path = (args.manifest or base_dir / "sources.manifest.json").resolve()

    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    ensure_layout(base_dir)
    manifest = load_manifest(manifest_path)
    sources = manifest.get("sources", [])

    downloads_log = base_dir / "metadata" / "downloads.jsonl"
    skipped_log = base_dir / "metadata" / "skipped.jsonl"
    run_log = {
        "timestamp": utc_now(),
        "base_dir": str(base_dir),
        "manifest": str(manifest_path),
        "dry_run": args.dry_run,
        "source_count": len(sources),
    }
    write_jsonl(base_dir / "metadata" / "runs.jsonl", run_log)

    for source in sources:
        record = {
            "timestamp": utc_now(),
            "id": source.get("id"),
            "kind": source.get("kind"),
            "bucket": source.get("bucket"),
            "url": source.get("url"),
        }
        try:
            result = process_source(base_dir, source, args.dry_run)
        except Exception as exc:
            result = {
                "status": "error",
                "source_id": source.get("id", "<unknown>"),
                "error": repr(exc),
            }
        record.update(result)

        if source.get("kind") == "youtube":
            for video_result in result.get("skipped_videos", []):
                write_jsonl(
                    skipped_log,
                    {
                        "timestamp": utc_now(),
                        "source_id": source.get("id"),
                        "kind": source.get("kind"),
                        "bucket": source.get("bucket"),
                        **video_result,
                    },
                )

        if result.get("status") == "ok":
            write_jsonl(downloads_log, record)
        elif result.get("status") in {"skipped", "dry-run"}:
            write_jsonl(skipped_log, record)
        else:
            write_jsonl(skipped_log, record)

        print(json.dumps(record, ensure_ascii=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
