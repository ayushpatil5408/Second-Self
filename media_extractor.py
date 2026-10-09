"""Media and file extraction engine for SecondSelf.

Extracts text, transcripts, descriptions, OCR, and technical metadata from:
- Images (PNG, JPG, WEBP, GIF, BMP, SVG): Groq Vision OCR/description + PIL/binary headers
- Audio (MP3, WAV, M4A, OGG, FLAC, AAC): Groq Whisper transcription + audio metadata
- Documents (PDF, DOCX, TXT, CSV, JSON, Markdown, Code): text extraction
- Video (MP4, MOV, WEBM) & Archives (ZIP, TAR): metadata and manifests
"""

from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Extensions grouped by category
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tiff", ".ico"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"}
DOC_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".csv", ".tsv", ".rtf"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".csv", ".tsv", ".html", ".xml",
    ".yaml", ".yml", ".js", ".ts", ".jsx", ".tsx", ".sh", ".bash",
    ".sql", ".css", ".scss", ".rst", ".ini", ".conf", ".env", ".toml"
}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}

MAX_EXTRACT_CHARS = 12000
MAX_IMAGE_FILE_SIZE = 20 * 1024 * 1024  # 20MB for Groq Vision
MAX_AUDIO_FILE_SIZE = 25 * 1024 * 1024  # 25MB for Groq Whisper


@dataclass
class MediaExtractionResult:
    media_category: str  # image, audio, video, document, text, archive, binary
    content_text: str    # Transcribed text, OCR text, doc content, or description
    summary: str         # Short 1-sentence summary
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    markdown_body: str = ""
    prompt_content: str = ""


def get_media_category(filename_or_path: str | Path) -> str:
    ext = Path(filename_or_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in DOC_EXTENSIONS:
        return "document"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    return "binary"


def get_mime_type(filename_or_path: str | Path) -> str:
    path = Path(filename_or_path)
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        return mime
    cat = get_media_category(path)
    ext = path.suffix.lower().lstrip(".")
    if cat == "image":
        return f"image/{ext or 'octet-stream'}"
    if cat == "audio":
        return f"audio/{ext or 'octet-stream'}"
    if cat == "video":
        return f"video/{ext or 'octet-stream'}"
    return "application/octet-stream"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


# ---------------------------------------------------------------------------
# Document Extractors: PDF & DOCX
# ---------------------------------------------------------------------------

def _extract_pdf_text_fallback(pdf_bytes: bytes) -> str:
    """Pure Python fallback to extract text streams from PDF bytes without external dependencies."""
    extracted_chunks = []
    # Search for compressed streams
    stream_pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    for match in stream_pattern.finditer(pdf_bytes):
        stream_data = match.group(1)
        decompressed = b""
        try:
            decompressed = zlib.decompress(stream_data)
        except Exception:
            try:
                decompressed = zlib.decompress(stream_data, -zlib.MAX_WBITS)
            except Exception:
                decompressed = stream_data

        # Look for PDF text operators (Tj, TJ, BT...ET)
        text_ops = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
        for t in text_ops:
            try:
                text_str = t.decode("latin1", errors="replace").strip()
                if text_str:
                    extracted_chunks.append(text_str)
            except Exception:
                pass

        # Also array texts: [(text) 120 (more)] TJ
        array_ops = re.findall(rb"\[(.*?)\]\s*TJ", decompressed)
        for arr in array_ops:
            sub_matches = re.findall(rb"\((.*?)\)", arr)
            line = "".join(m.decode("latin1", errors="replace") for m in sub_matches)
            if line.strip():
                extracted_chunks.append(line.strip())

    return "\n".join(extracted_chunks)


def extract_pdf_content(path: Path) -> tuple[str, dict[str, Any]]:
    """Extract text and metadata from a PDF file."""
    metadata: dict[str, Any] = {"format": "PDF", "file_size": path.stat().st_size}
    text_parts: list[str] = []

    # 1. Try pypdf / PyPDF2
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        metadata["pages"] = len(reader.pages)
        if reader.metadata:
            if reader.metadata.title:
                metadata["title"] = reader.metadata.title
            if reader.metadata.author:
                metadata["author"] = reader.metadata.author
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{txt.strip()}")
    except Exception:
        # 2. Try PyPDF2
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(path))
            metadata["pages"] = len(reader.pages)
            for i, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    text_parts.append(f"--- Page {i + 1} ---\n{txt.strip()}")
        except Exception:
            # 3. Pure Python stream extractor
            try:
                data = path.read_bytes()
                extracted = _extract_pdf_text_fallback(data)
                if extracted:
                    text_parts.append(extracted)
            except Exception as exc:
                metadata["extract_error"] = str(exc)

    full_text = "\n\n".join(text_parts).strip()
    return full_text, metadata


def extract_docx_content(path: Path) -> tuple[str, dict[str, Any]]:
    """Extract text from a DOCX file using python-docx or standard library zipfile."""
    metadata: dict[str, Any] = {"format": "DOCX", "file_size": path.stat().st_size}
    text_parts: list[str] = []

    # 1. Try python-docx
    try:
        import docx
        doc = docx.Document(str(path))
        for p in doc.paragraphs:
            if p.text.strip():
                text_parts.append(p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(f"| {row_text} |")
    except Exception:
        # 2. Standard library zipfile fallback (parses word/document.xml)
        try:
            import xml.etree.ElementTree as ET
            import zipfile
            with zipfile.ZipFile(path) as z:
                xml_content = z.read("word/document.xml")
                root = ET.fromstring(xml_content)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for p in root.iter(f"{{{ns['w']}}}p"):
                    texts = [t.text for t in p.iter(f"{{{ns['w']}}}t") if t.text]
                    line = "".join(texts).strip()
                    if line:
                        text_parts.append(line)
        except Exception as exc:
            metadata["extract_error"] = str(exc)

    return "\n\n".join(text_parts).strip(), metadata


# ---------------------------------------------------------------------------
# Image Extractors: Dimensions + Groq Multimodal Vision OCR
# ---------------------------------------------------------------------------

def _extract_image_dimensions_fallback(data: bytes, ext: str) -> tuple[int | None, int | None]:
    """Pure Python header parser for image width & height without Pillow."""
    try:
        # PNG: bytes 16-24 have width and height as 4-byte big-endian ints
        if ext == ".png" and len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
            return w, h

        # GIF: bytes 6-10 have width and height as 2-byte little-endian ints
        if ext == ".gif" and len(data) >= 10 and data[:3] == b"GIF":
            w, h = struct.unpack("<HH", data[6:10])
            return w, h

        # JPEG: find SOF0/SOF2 marker
        if ext in {".jpg", ".jpeg"} and len(data) >= 4 and data[:2] == b"\xff\xd8":
            idx = 2
            while idx < len(data) - 8:
                if data[idx] != 0xFF:
                    idx += 1
                    continue
                marker = data[idx + 1]
                # SOF markers: 0xC0 .. 0xC3
                if marker in {0xC0, 0xC1, 0xC2, 0xC3}:
                    h, w = struct.unpack(">HH", data[idx + 5 : idx + 9])
                    return w, h
                length = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
                idx += 2 + length
    except Exception:
        pass
    return None, None


def extract_image_specs(path: Path) -> dict[str, Any]:
    """Extract format, width, height, and color mode."""
    specs: dict[str, Any] = {
        "file_size": path.stat().st_size,
        "format": path.suffix.lstrip(".").upper(),
    }
    data = path.read_bytes()
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            specs["width"] = img.width
            specs["height"] = img.height
            specs["mode"] = img.mode
            specs["aspect_ratio"] = f"{img.width}:{img.height}"
            if hasattr(img, "format") and img.format:
                specs["format"] = img.format
    except Exception:
        w, h = _extract_image_dimensions_fallback(data, path.suffix.lower())
        if w and h:
            specs["width"] = w
            specs["height"] = h
            specs["aspect_ratio"] = f"{w}:{h}"
    return specs


def analyze_image_with_groq_vision(path: Path, api_key: str | None = None) -> tuple[str, list[str]]:
    """Use Groq Multimodal Vision (llama-3.2-11b-vision-preview) to describe image and extract OCR text."""
    try:
        from ask import resolve_groq_api_key
        key = resolve_groq_api_key(api_key)
        if not key:
            return "", []

        from groq import Groq
        client = Groq(api_key=key, timeout=25.0)

        data = path.read_bytes()
        if len(data) > MAX_IMAGE_FILE_SIZE:
            return "", []

        mime = get_mime_type(path)
        b64_data = base64.b64encode(data).decode("utf-8")
        data_url = f"data:{mime};base64,{b64_data}"

        prompt = (
            "Analyze this image in detail for a personal second brain / knowledge base:\n"
            "1. Detailed Description: Describe the scene, content, diagram, layout, or objects.\n"
            "2. Visible Text / OCR: Transcribe all visible text, titles, numbers, labels, or captions verbatim.\n"
            "3. Key Concepts: 3-5 keywords or topics.\n"
            "Format your response clearly with markdown."
        )

        response = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        text = response.choices[0].message.content or ""
        tags = ["image", "visual-capture"]
        if "ocr" in text.lower() or "text" in text.lower():
            tags.append("ocr")
        return text.strip(), tags
    except Exception:
        return "", []


# ---------------------------------------------------------------------------
# Audio Extractors: Transcription via Groq Whisper
# ---------------------------------------------------------------------------

def transcribe_audio_with_groq_whisper(path: Path, api_key: str | None = None) -> tuple[str, dict[str, Any], list[str]]:
    """Transcribe audio file using Groq Whisper API (whisper-large-v3-turbo)."""
    meta: dict[str, Any] = {"format": path.suffix.lstrip(".").upper(), "file_size": path.stat().st_size}
    tags = ["audio", "voice-note"]

    try:
        from ask import resolve_groq_api_key
        key = resolve_groq_api_key(api_key)
        if not key:
            return "", meta, tags

        from groq import Groq
        client = Groq(api_key=key, timeout=60.0)

        file_size = path.stat().st_size
        if file_size > MAX_AUDIO_FILE_SIZE:
            meta["transcribe_error"] = f"File exceeds 25MB Groq Whisper limit ({_format_size(file_size)})"
            return "", meta, tags

        with open(path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(path.name, f.read()),
                model="whisper-large-v3-turbo",
                response_format="verbose_json",
            )

        transcript_text = getattr(transcription, "text", "") or ""
        if hasattr(transcription, "language") and transcription.language:
            meta["language"] = transcription.language
        if hasattr(transcription, "duration") and transcription.duration:
            meta["duration_seconds"] = round(float(transcription.duration), 1)

        tags.append("transcript")
        return transcript_text.strip(), meta, tags
    except Exception as exc:
        meta["transcribe_error"] = str(exc)
        return "", meta, tags


# ---------------------------------------------------------------------------
# Text, Code, CSV, and Archive Extractors
# ---------------------------------------------------------------------------

def extract_text_file_content(path: Path) -> tuple[str, dict[str, Any]]:
    """Extract and analyze plain text, markdown, CSV, JSON, code."""
    meta: dict[str, Any] = {"format": path.suffix.lstrip(".").upper(), "file_size": path.stat().st_size}
    raw_bytes = path.read_bytes()

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("latin-1")
        except Exception:
            text = str(raw_bytes[:MAX_EXTRACT_CHARS])

    ext = path.suffix.lower()
    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
            meta["rows"] = len(rows)
            if rows:
                meta["columns"] = len(rows[0])
                header = rows[0]
                sample = "\n".join([f"Columns: {', '.join(header)}", f"Total rows: {len(rows)}"])
                return f"{sample}\n\nContent:\n{text[:MAX_EXTRACT_CHARS]}", meta
        except Exception:
            pass

    if ext == ".json":
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                meta["keys"] = list(obj.keys())[:15]
            elif isinstance(obj, list):
                meta["item_count"] = len(obj)
        except Exception:
            pass

    return text[:MAX_EXTRACT_CHARS], meta


def extract_archive_content(path: Path) -> tuple[str, dict[str, Any]]:
    """Extract file list and manifest from an archive."""
    meta: dict[str, Any] = {"format": path.suffix.lstrip(".").upper(), "file_size": path.stat().st_size}
    ext = path.suffix.lower()
    lines = []
    if ext == ".zip":
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                files = z.infolist()
                meta["file_count"] = len(files)
                lines.append(f"Archive contains {len(files)} files:")
                for item in files[:50]:
                    lines.append(f"- `{item.filename}` ({_format_size(item.file_size)})")
        except Exception as exc:
            lines.append(f"Error reading zip: {exc}")
    elif ext in {".tar", ".gz", ".tgz"}:
        try:
            import tarfile
            with tarfile.open(path) as t:
                members = t.getmembers()
                meta["file_count"] = len(members)
                lines.append(f"Archive contains {len(members)} files:")
                for item in members[:50]:
                    lines.append(f"- `{item.name}` ({_format_size(item.size)})")
        except Exception as exc:
            lines.append(f"Error reading archive: {exc}")

    return "\n".join(lines), meta


# ---------------------------------------------------------------------------
# Master Ingestion Analyzer
# ---------------------------------------------------------------------------

def extract_media(
    raw_path: Path,
    api_key: str | None = None,
    caption: str = "",
) -> MediaExtractionResult:
    """Analyze any media or document file and return an enriched extraction result."""
    raw_path = Path(raw_path).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    category = get_media_category(raw_path)
    file_size = raw_path.stat().st_size
    formatted_size = _format_size(file_size)
    ext = raw_path.suffix.lower()
    name = raw_path.name

    # Look up original metadata if available
    meta_path = raw_path.with_suffix(".meta.json")
    original_meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            original_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    original_name = original_meta.get("extra", {}).get("original_name", name)
    user_caption = caption or original_meta.get("extra", {}).get("caption", "")

    content_text = ""
    specs: dict[str, Any] = {}
    tags: list[str] = [category]

    # Process based on category
    if category == "image":
        specs = extract_image_specs(raw_path)
        vision_text, vision_tags = analyze_image_with_groq_vision(raw_path, api_key=api_key)
        tags.extend(vision_tags)
        if vision_text:
            content_text = vision_text
        else:
            dim_str = f"{specs.get('width', '?')}x{specs.get('height', '?')}"
            content_text = f"Image file '{original_name}' ({specs.get('format', 'IMG')}, {dim_str}, {formatted_size})."

    elif category == "audio":
        transcript, audio_meta, audio_tags = transcribe_audio_with_groq_whisper(raw_path, api_key=api_key)
        specs.update(audio_meta)
        tags.extend(audio_tags)
        if transcript:
            content_text = transcript
        else:
            content_text = f"Audio recording '{original_name}' ({formatted_size})."

    elif category == "document":
        if ext == ".pdf":
            content_text, specs = extract_pdf_content(raw_path)
            tags.extend(["document", "pdf"])
        elif ext in {".docx", ".doc"}:
            content_text, specs = extract_docx_content(raw_path)
            tags.extend(["document", "docx"])
        else:
            content_text, specs = extract_text_file_content(raw_path)
            tags.extend(["document"])

    elif category == "text":
        content_text, specs = extract_text_file_content(raw_path)
        tags.extend(["text", ext.lstrip(".")])

    elif category == "archive":
        content_text, specs = extract_archive_content(raw_path)
        tags.extend(["archive"])

    else:
        content_text = f"Binary file '{original_name}' ({ext or 'unknown type'}, {formatted_size})."
        tags.append("file")

    specs["original_name"] = original_name
    specs["file_size"] = file_size
    specs["formatted_size"] = formatted_size
    specs["media_category"] = category
    specs["mime_type"] = get_mime_type(original_name)

    # Build concise summary
    if user_caption:
        summary = f"{user_caption} ({original_name})"
    elif content_text and len(content_text.strip()) > 10:
        first_line = content_text.strip().splitlines()[0]
        summary = re.sub(r"^#+\s*", "", first_line)[:110]
    else:
        summary = f"Uploaded {category}: {original_name}"

    # Build markdown body for wiki note
    body_lines = [f"# {original_name}\n"]

    # Media preview / badge
    raw_rel = f"raw/{raw_path.name}"
    if category == "image":
        body_lines.append(f"![{original_name}](../../{raw_rel})\n")
    elif category == "audio":
        body_lines.append(f"> 🎵 **Audio Recording:** `{original_name}` ({formatted_size})\n")
    elif category == "video":
        body_lines.append(f"> 🎬 **Video File:** `{original_name}` ({formatted_size})\n")
    elif category == "document":
        body_lines.append(f"> 📄 **Document:** `{original_name}` ({formatted_size})\n")
    else:
        body_lines.append(f"> 📁 **File:** `{original_name}` ({formatted_size})\n")

    if user_caption:
        body_lines.append(f"### User Note\n{user_caption}\n")

    if category in {"image", "audio"} and content_text:
        header = "Visual Analysis & OCR" if category == "image" else "Audio Transcription"
        body_lines.append(f"### {header}\n{content_text}\n")
    elif content_text:
        body_lines.append(f"### Content\n{content_text}\n")

    # Technical metadata block
    body_lines.append("### Technical Metadata\n")
    body_lines.append(f"- **Filename:** `{original_name}`")
    body_lines.append(f"- **Category:** `{category}`")
    body_lines.append(f"- **Size:** {formatted_size}")
    body_lines.append(f"- **Stored As:** `{raw_rel}`")
    for k, v in specs.items():
        if k not in {"original_name", "file_size", "formatted_size", "media_category", "mime_type"} and v:
            body_lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")

    markdown_body = "\n".join(body_lines) + "\n"

    # LLM prompt content for classification
    prompt_lines = [
        f"Media capture of type: {category.upper()}",
        f"Filename: {original_name}",
        f"Size: {formatted_size}",
    ]
    if user_caption:
        prompt_lines.append(f"User caption/notes: {user_caption}")
    if content_text:
        prompt_lines.append(f"\nExtracted Content / Transcript / Vision Analysis:\n---\n{content_text[:6000]}\n---")

    prompt_content = "\n".join(prompt_lines)

    # Clean tags
    clean_tags = []
    for t in tags:
        t_clean = re.sub(r"[^\w-]", "", t.lower().strip())
        if t_clean and t_clean not in clean_tags:
            clean_tags.append(t_clean)

    return MediaExtractionResult(
        media_category=category,
        content_text=content_text,
        summary=summary,
        tags=clean_tags,
        metadata=specs,
        markdown_body=markdown_body,
        prompt_content=prompt_content,
    )


def resolve_media_file(src: Any, raw_dir: Path | None = None) -> tuple[str, Path | None, str]:
    """Locate the media file on disk, category, and display name for a retrieved note or dict."""
    from config import PROJECT_ROOT, RAW_DIR

    target_raw = raw_dir if raw_dir is not None else RAW_DIR

    note_id = getattr(src, "note_id", "") if hasattr(src, "note_id") else src.get("note_id", "")
    raw_ref = (getattr(src, "raw_ref", None) if hasattr(src, "raw_ref") else src.get("raw_ref")) or ""
    original_name = (getattr(src, "original_name", None) if hasattr(src, "original_name") else src.get("original_name")) or ""
    body = getattr(src, "body", "") if hasattr(src, "body") else src.get("body", "")
    slug = getattr(src, "slug", "") if hasattr(src, "slug") else src.get("slug", "media")
    media_type = getattr(src, "media_type", None) if hasattr(src, "media_type") else src.get("media_type")

    candidates: list[Path] = []
    if raw_ref:
        candidates.append(target_raw / Path(raw_ref).name)
        candidates.append(RAW_DIR / Path(raw_ref).name)
        candidates.append(PROJECT_ROOT / raw_ref)
        candidates.append(PROJECT_ROOT / "raw" / Path(raw_ref).name)

    if note_id and target_raw.exists():
        candidates.extend(sorted(target_raw.glob(f"*_{note_id}.*")))
    if note_id and RAW_DIR.exists():
        candidates.extend(sorted(RAW_DIR.glob(f"*_{note_id}.*")))

    if body:
        match_img = re.search(r"!\[(.*?)\]\((.*?raw/([^\)]+))\)", body)
        if match_img:
            raw_img_name = match_img.group(3)
            candidates.append(target_raw / raw_img_name)
            candidates.append(RAW_DIR / raw_img_name)
            candidates.append(PROJECT_ROOT / "raw" / raw_img_name)
            if not original_name:
                original_name = match_img.group(1)

        match_ref = re.search(r"raw/([a-zA-Z0-9_\-\.]+)", body)
        if match_ref:
            raw_file_name = match_ref.group(1)
            candidates.append(target_raw / raw_file_name)
            candidates.append(RAW_DIR / raw_file_name)
            candidates.append(PROJECT_ROOT / "raw" / raw_file_name)

    found_path: Path | None = None
    for p in candidates:
        if p and p.exists() and p.is_file() and not p.name.endswith(".meta.json"):
            found_path = p
            break

    # Resolve category
    category = media_type
    if not category and found_path:
        category = get_media_category(found_path.name)
    if not category and original_name:
        category = get_media_category(original_name)
    if not category and raw_ref:
        category = get_media_category(raw_ref)

    display_name = original_name or (found_path.name if found_path else slug)
    return category or "file", found_path, display_name

