from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from config import RAW_DIR


@dataclass
class CaptureRecord:
    id: str
    timestamp: str
    capture_type: str
    source: str
    file_path: Path
    metadata_path: Path
    extra: dict[str, Any]


def generate_id() -> str:
    return uuid.uuid4().hex[:8]


def make_filename(timestamp: datetime, id: str, ext: str) -> str:
    return f"{timestamp:%Y%m%d}_{timestamp:%H%M%S}_{id}.{ext}"


def _write_metadata(record: CaptureRecord) -> Path:
    metadata = {
        "id": record.id,
        "timestamp": record.timestamp,
        "capture_type": record.capture_type,
        "source": record.source,
        "file_path": str(record.file_path.name),
        "extra": record.extra,
    }
    metadata_path = record.file_path.with_suffix(".meta.json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_path


def _fetch_url_title(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "SecondSelf/1.0"})
        response.raise_for_status()
        html = response.text
        match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            title = match.group(1).strip()
            return re.sub(r"\s+", " ", title)
    except requests.RequestException:
        pass
    return None


def _make_record(
    capture_id: str,
    timestamp: datetime,
    capture_type: str,
    source: str,
    filename: str,
    extra: dict[str, Any],
) -> CaptureRecord:
    file_path = RAW_DIR / filename
    record = CaptureRecord(
        id=capture_id,
        timestamp=timestamp.isoformat(),
        capture_type=capture_type,
        source=source,
        file_path=file_path,
        metadata_path=file_path.with_suffix(".meta.json"),
        extra=extra,
    )
    _write_metadata(record)
    return record


def save_capture(content: str, capture_type: str, source: str, ext: str = "txt", extra: dict[str, Any] | None = None) -> CaptureRecord:
    if extra is None:
        extra = {}
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    capture_id = generate_id()
    filename = make_filename(timestamp, capture_id, ext)
    path = RAW_DIR / filename
    path.write_text(content, encoding="utf-8")
    return _make_record(capture_id, timestamp, capture_type, source, filename, extra)


def capture_note(text: str, source: str = "cli") -> CaptureRecord:
    content = text.strip() + "\n"
    return save_capture(content, "note", source, ext="txt", extra={"preview": content[:240]})


def capture_link(url: str, source: str = "cli") -> CaptureRecord:
    title = _fetch_url_title(url)
    lines = [f"URL: {url}"]
    if title:
        lines.append(f"TITLE: {title}")
    lines.append("")
    lines.append(url)
    content = "\n".join(lines) + "\n"
    extra: dict[str, Any] = {"url": url}
    if title:
        extra["title"] = title
    return save_capture(content, "link", source, ext="txt", extra=extra)


def capture_file(path: str, source: str = "cli") -> CaptureRecord:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    capture_id = generate_id()
    ext = source_path.suffix.lstrip(".") or "bin"
    filename = make_filename(timestamp, capture_id, ext)
    destination = RAW_DIR / filename
    shutil.copy2(source_path, destination)
    extra = {
        "original_path": str(source_path),
        "original_name": source_path.name,
    }
    return _make_record(capture_id, timestamp, "file", source, filename, extra)


def capture_stdin(source: str = "stdin") -> CaptureRecord:
    raw_text = sys.stdin.read()
    if not raw_text.strip():
        raise ValueError("No text was provided on stdin.")
    return capture_note(raw_text, source=source)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture notes, links, and files into raw/.")
    parser.add_argument("text", nargs="*", help="Plain note text to capture.")
    parser.add_argument("--link", "-l", help="Capture a URL as a link.")
    parser.add_argument("--file", "-f", help="Capture an existing file into raw/.")
    parser.add_argument("--stdin", action="store_true", help="Capture text from stdin.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.stdin or (not sys.stdin.isatty() and not any((args.link, args.file, args.text))):
            record = capture_stdin()
        elif args.link:
            if args.text:
                raise ValueError("Cannot capture note text and a link in the same command.")
            record = capture_link(args.link)
        elif args.file:
            if args.text:
                raise ValueError("Cannot capture note text and a file in the same command.")
            record = capture_file(args.file)
        elif args.text:
            text = " ".join(args.text).strip()
            if not text:
                raise ValueError("Note text must not be empty.")
            record = capture_note(text)
        else:
            raise ValueError("Provide a note, --link URL, --file PATH, or use --stdin/piped input.")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Captured {record.capture_type} -> {record.file_path}")
    print(f"Metadata -> {record.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
