from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
try:
    from datetime import UTC, datetime
except ImportError:
    from datetime import datetime, timezone
    UTC = timezone.utc
from pathlib import Path
from typing import Any

import requests

from config import RAW_DIR
from media_extractor import get_media_category, get_mime_type


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


def capture_media(
    data_or_path: bytes | Path | str,
    original_filename: str = "",
    source: str = "cli",
    caption: str = "",
) -> CaptureRecord:
    """Capture a file or media stream (image, audio, document, video) into raw/."""
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    capture_id = generate_id()

    if isinstance(data_or_path, (str, Path)):
        source_path = Path(data_or_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        original_name = original_filename or source_path.name
        ext = source_path.suffix.lstrip(".") or "bin"
        filename = make_filename(timestamp, capture_id, ext)
        destination = RAW_DIR / filename
        shutil.copy2(source_path, destination)
        file_size = destination.stat().st_size
    else:
        # Raw bytes from upload
        original_name = original_filename or f"upload_{capture_id}.bin"
        ext = Path(original_name).suffix.lstrip(".") or "bin"
        filename = make_filename(timestamp, capture_id, ext)
        destination = RAW_DIR / filename
        destination.write_bytes(data_or_path)
        file_size = len(data_or_path)

    category = get_media_category(original_name)
    mime_type = get_mime_type(original_name)

    extra: dict[str, Any] = {
        "original_name": original_name,
        "media_category": category,
        "mime_type": mime_type,
        "file_size": file_size,
    }
    if caption:
        extra["caption"] = caption
        extra["preview"] = f"{caption} ({original_name})"
    else:
        extra["preview"] = f"Captured {category}: {original_name}"

    capture_type = "media" if category in {"image", "audio", "video"} else "file"
    return _make_record(capture_id, timestamp, capture_type, source, filename, extra)


def capture_file(path: str, source: str = "cli", caption: str = "") -> CaptureRecord:
    """Capture an existing file into raw/."""
    return capture_media(path, source=source, caption=caption)


def capture_stdin(source: str = "stdin") -> CaptureRecord:
    raw_text = sys.stdin.read()
    if not raw_text.strip():
        raise ValueError("No text was provided on stdin.")
    return capture_note(raw_text, source=source)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture notes, links, and media/files into raw/.")
    parser.add_argument("text", nargs="*", help="Plain note text to capture.")
    parser.add_argument("--link", "-l", help="Capture a URL as a link.")
    parser.add_argument("--file", "-f", help="Capture an existing file into raw/.")
    parser.add_argument("--media", "-m", help="Capture an image, audio, or media file into raw/.")
    parser.add_argument("--caption", "-c", default="", help="Optional caption or note describing the file.")
    parser.add_argument("--stdin", action="store_true", help="Capture text from stdin.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_file = args.media or args.file
    try:
        if args.stdin or (not sys.stdin.isatty() and not any((args.link, target_file, args.text))):
            record = capture_stdin()
        elif args.link:
            if args.text or target_file:
                raise ValueError("Cannot capture note/file and a link in the same command.")
            record = capture_link(args.link)
        elif target_file:
            if args.text:
                raise ValueError("Cannot capture note text and a file in the same command.")
            record = capture_media(target_file, caption=args.caption)
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
