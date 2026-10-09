from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter
from dotenv import load_dotenv
from groq import Groq

from config import EMBEDDING_MODEL, LLM_MODEL, PROJECT_ROOT, RAW_DIR, WIKI_DIR
from media_extractor import extract_media, get_media_category, get_mime_type

PARA_CATEGORIES = ("Projects", "Areas", "Resources", "Archives")
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".json", ".csv", ".html", ".xml", ".yaml", ".yml"}
MAX_CLASSIFY_CHARS = 8000
MAX_SUMMARY_CHARS = 120
MAX_TAGS = 10

PARA_ALIASES = {
    "project": "Projects",
    "projects": "Projects",
    "area": "Areas",
    "areas": "Areas",
    "resource": "Resources",
    "resources": "Resources",
    "archive": "Archives",
    "archives": "Archives",
}

SYSTEM_PROMPT = (
    "You are a knowledge librarian. Classify content using PARA: "
    "Projects (active outcomes), Areas (ongoing responsibilities), "
    "Resources (reference/interest), Archives (inactive/completed). "
    "Return valid JSON only."
)

USER_PROMPT = """Classify the following raw capture. Return JSON with exactly these keys:
- "para": one of "Projects", "Areas", "Resources", "Archives"
- "tags": array of lowercase tags (1-5 items)
- "summary": one-line summary under 120 characters
- "slug": kebab-case-title suitable for a filename

Raw content:
---
{content}
---

Return valid JSON only, no markdown fences."""

STRICT_RETRY_PROMPT = """Your previous response was not valid JSON. Return ONLY a JSON object with keys:
"para", "tags", "summary", "slug". No prose, no markdown fences.

Raw content:
---
{content}
---"""


@dataclass
class ClassificationResult:
    para: str
    tags: list[str]
    summary: str
    slug: str


def _get_groq_client(api_key: str | None = None) -> Groq:
    """Initialize and return a Groq client with API key from env, session, or secrets."""
    from ask import resolve_groq_api_key

    resolved = resolve_groq_api_key(api_key)
    if not resolved:
        error_msg = (
            "GROQ_API_KEY is not set or is invalid.\n"
            "Options:\n"
            "1. Local: Add GROQ_API_KEY to .env file\n"
            "2. Streamlit UI: Add GROQ_API_KEY in the sidebar\n"
            "3. Streamlit Cloud: Add GROQ_API_KEY in Secrets tab\n"
            "4. Docker/Container: Set GROQ_API_KEY environment variable"
        )
        raise RuntimeError(error_msg)

    return Groq(api_key=resolved, timeout=15.0)


def normalize_raw_ref(raw_ref: str | Path) -> str:
    ref = str(raw_ref).replace("\\", "/")
    if ref.startswith("raw/"):
        return ref
    return f"raw/{Path(ref).name}"


def extract_capture_id(raw_path: Path) -> str:
    parts = raw_path.stem.split("_")
    if len(parts) >= 3 and re.fullmatch(r"[0-9a-f]{8}", parts[2]):
        return parts[2]
    meta_path = raw_path.with_suffix(".meta.json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))["id"]
    raise ValueError(f"Cannot extract capture ID from {raw_path.name}")


def extract_created(raw_path: Path) -> str:
    meta_path = raw_path.with_suffix(".meta.json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))["timestamp"]
    parts = raw_path.stem.split("_")
    if len(parts) >= 2:
        created = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
        return created.isoformat()
    return datetime.now().isoformat()


def sanitize_slug(slug: str, fallback: str = "note") -> str:
    cleaned = slug.lower().strip()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:80]


def slug_from_filename(raw_path: Path) -> str:
    capture_id = extract_capture_id(raw_path)
    return sanitize_slug(f"capture-{capture_id}", fallback=f"capture-{capture_id}")


def is_raw_capture(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name == ".gitkeep" or path.name.endswith(".meta.json"):
        return False
    return True


def normalize_para(para: str) -> str:
    if para in PARA_CATEGORIES:
        return para
    mapped = PARA_ALIASES.get(para.strip().lower())
    if mapped:
        return mapped
    return "Resources"


def normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    normalized: list[str] = []
    for tag in tags[:MAX_TAGS]:
        if not isinstance(tag, str):
            continue
        cleaned = sanitize_slug(tag, fallback="")
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _truncate_summary(summary: str) -> str:
    summary = " ".join(summary.split())
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    return summary[: MAX_SUMMARY_CHARS - 3].rstrip() + "..."


def _read_metadata(raw_path: Path) -> dict[str, Any]:
    meta_path = raw_path.with_suffix(".meta.json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def read_raw_content(raw_path: Path) -> tuple[str, str]:
    """Return LLM prompt content and markdown body for the wiki note."""
    if raw_path.stat().st_size == 0:
        raise ValueError(f"Raw file is empty: {raw_path.name}")

    metadata = _read_metadata(raw_path)
    capture_type = metadata.get("capture_type", "")
    caption = metadata.get("extra", {}).get("caption", "")
    ext = raw_path.suffix.lower()

    # If it's a file/media capture or not a plain text extension, extract deeply
    if capture_type in {"file", "media"} or ext not in TEXT_EXTENSIONS:
        try:
            from ask import resolve_groq_api_key
            api_key = resolve_groq_api_key()
        except Exception:
            api_key = None

        extracted = extract_media(raw_path, api_key=api_key, caption=caption)
        return extracted.prompt_content, extracted.markdown_body

    # For standard plain-text note/link captures
    try:
        text = raw_path.read_text(encoding="utf-8")
        body = text.rstrip() + "\n"
        prompt_text = text[:MAX_CLASSIFY_CHARS]
        if len(text) > MAX_CLASSIFY_CHARS:
            prompt_text += "\n\n[truncated]"
        return prompt_text, body
    except UnicodeDecodeError:
        pass

    extracted = extract_media(raw_path, caption=caption)
    return extracted.prompt_content, extracted.markdown_body


def _fallback_classification(raw_path: Path) -> ClassificationResult:
    capture_id = extract_capture_id(raw_path)
    slug = slug_from_filename(raw_path)
    metadata = _read_metadata(raw_path)
    caption = metadata.get("extra", {}).get("caption", "")

    extracted = extract_media(raw_path, caption=caption)
    summary = extracted.summary or metadata.get("extra", {}).get("preview", "").strip() or f"Captured: {raw_path.name}"
    tags = extracted.tags or (["unparsed-file"] if raw_path.suffix.lower() not in TEXT_EXTENSIONS else [])

    return ClassificationResult(
        para="Resources",
        tags=tags,
        summary=_truncate_summary(summary),
        slug=sanitize_slug(slug, fallback=f"capture-{capture_id}"),
    )


def _classification_from_dict(data: dict[str, Any], raw_path: Path) -> ClassificationResult:
    capture_id = extract_capture_id(raw_path)
    fallback_slug = slug_from_filename(raw_path)
    para = normalize_para(str(data.get("para", "Resources")))
    tags = normalize_tags(data.get("tags", []))
    summary = _truncate_summary(str(data.get("summary", "")).strip() or f"Captured: {raw_path.name}")
    slug = sanitize_slug(str(data.get("slug", "")), fallback=fallback_slug)
    slug = resolve_slug_collision(slug, para, capture_id)
    return ClassificationResult(para=para, tags=tags, summary=summary, slug=slug)


def resolve_slug_collision(slug: str, para: str, capture_id: str) -> str:
    target = WIKI_DIR / para / f"{slug}.md"
    if not target.exists():
        return slug
    post = frontmatter.load(target)
    if post.get("id") == capture_id:
        return slug
    return sanitize_slug(f"{slug}-{capture_id}", fallback=f"capture-{capture_id}")


def call_llm(content: str, *, retry: bool = False) -> dict[str, Any]:
    client = _get_groq_client()
    prompt = STRICT_RETRY_PROMPT.format(content=content) if retry else USER_PROMPT.format(content=content)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            message = response.choices[0].message.content or ""
            return parse_llm_json(message)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            err_str = str(exc)
            if status == 401 or "invalid_api_key" in err_str.lower() or "authentication" in err_str.lower():
                raise RuntimeError("Invalid Groq API key") from exc
            if status == 429 and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("Groq API call failed after retries")


def classify_capture(raw_path: Path) -> ClassificationResult:
    raw_path = raw_path.resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    prompt_content, _ = read_raw_content(raw_path)
    try:
        data = call_llm(prompt_content)
        return _classification_from_dict(data, raw_path)
    except Exception:
        try:
            data = call_llm(prompt_content, retry=True)
            return _classification_from_dict(data, raw_path)
        except Exception:
            return _fallback_classification(raw_path)


def get_processed_raw_refs(wiki_dir: Path | None = None) -> set[str]:
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    refs: set[str] = set()
    if not target_wiki.exists():
        return refs
    for wiki_path in target_wiki.rglob("*.md"):
        try:
            post = frontmatter.load(wiki_path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        raw_ref = post.get("raw_ref")
        if raw_ref:
            refs.add(normalize_raw_ref(raw_ref))
    return refs


def find_wiki_note_by_raw_ref(raw_ref: str, wiki_dir: Path | None = None) -> Path | None:
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    normalized = normalize_raw_ref(raw_ref)
    if not target_wiki.exists():
        return None
    for wiki_path in target_wiki.rglob("*.md"):
        try:
            post = frontmatter.load(wiki_path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if normalize_raw_ref(post.get("raw_ref", "")) == normalized:
            return wiki_path
    return None


def get_unprocessed_raw(*, force: bool = False, raw_dir: Path | None = None, wiki_dir: Path | None = None) -> list[Path]:
    target_raw = raw_dir if raw_dir is not None else RAW_DIR
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    processed = set() if force else get_processed_raw_refs(target_wiki)
    candidates: list[Path] = []
    if not target_raw.exists():
        return candidates
    for path in sorted(target_raw.iterdir()):
        if not is_raw_capture(path):
            continue
        raw_ref = normalize_raw_ref(f"raw/{path.name}")
        if raw_ref not in processed:
            candidates.append(path)
    return candidates


def write_wiki_note(raw_path: Path, classification: ClassificationResult, body: str, wiki_dir: Path | None = None) -> Path:
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    capture_id = extract_capture_id(raw_path)
    raw_ref = normalize_raw_ref(f"raw/{raw_path.name}")
    created = extract_created(raw_path)
    metadata = _read_metadata(raw_path)

    post = frontmatter.Post(body.rstrip() + "\n")
    meta_dict: dict[str, Any] = {
        "id": capture_id,
        "raw_ref": raw_ref,
        "para": classification.para,
        "tags": classification.tags,
        "summary": classification.summary,
        "created": created,
        "links": [],
        "embedding_model": EMBEDDING_MODEL,
    }

    # Add media-specific frontmatter attributes if applicable
    extra = metadata.get("extra", {})
    category = extra.get("media_category") or get_media_category(raw_path)
    if metadata.get("capture_type") in {"file", "media"} or category in {"image", "audio", "video", "document"}:
        meta_dict["media_type"] = category
        meta_dict["original_name"] = extra.get("original_name", raw_path.name)
        meta_dict["file_size"] = extra.get("file_size", raw_path.stat().st_size)
        meta_dict["mime_type"] = extra.get("mime_type", get_mime_type(raw_path))

    post.metadata = meta_dict

    wiki_path = target_wiki / classification.para / f"{classification.slug}.md"
    wiki_path.parent.mkdir(parents=True, exist_ok=True)
    wiki_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return wiki_path


def process_raw_file(raw_path: Path, *, force: bool = False, wiki_dir: Path | None = None) -> Path | None:
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    raw_path = raw_path.resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    raw_ref = normalize_raw_ref(f"raw/{raw_path.name}")
    existing = find_wiki_note_by_raw_ref(raw_ref, target_wiki)
    if existing and not force:
        print(f"Skip (already classified): {raw_path.name}")
        return None

    try:
        _, body = read_raw_content(raw_path)
    except ValueError as exc:
        print(f"Warning: {exc}", file=sys.stderr)
        return None

    classification = classify_capture(raw_path)
    wiki_path = write_wiki_note(raw_path, classification, body, target_wiki)

    if existing and existing.resolve() != wiki_path.resolve():
        existing.unlink()
        try:
            print(f"Removed old wiki note: {existing.relative_to(PROJECT_ROOT)}")
        except Exception:
            pass

    try:
        rel_path = wiki_path.relative_to(PROJECT_ROOT)
    except Exception:
        rel_path = wiki_path
    print(f"Classified {raw_path.name} -> {rel_path} [{classification.para}]")
    return wiki_path


def process_all_unclassified(*, force: bool = False, raw_dir: Path | None = None, wiki_dir: Path | None = None) -> list[Path]:
    target_raw = raw_dir if raw_dir is not None else RAW_DIR
    target_wiki = wiki_dir if wiki_dir is not None else WIKI_DIR
    raw_files = get_unprocessed_raw(force=force, raw_dir=target_raw, wiki_dir=target_wiki)
    if not raw_files:
        print("No unclassified raw captures found.")
        return []

    results: list[Path] = []
    failures = 0
    for raw_path in raw_files:
        try:
            wiki_path = process_raw_file(raw_path, force=force, wiki_dir=target_wiki)
            if wiki_path:
                results.append(wiki_path)
        except Exception as exc:
            failures += 1
            print(f"Error classifying {raw_path.name}: {exc}", file=sys.stderr)

    print(f"Done: {len(results)} classified, {failures} failed, {len(raw_files) - len(results) - failures} skipped.")
    if failures and not results:
        raise SystemExit(1)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify raw captures into PARA-organized wiki notes.")
    parser.add_argument("--file", "-f", help="Classify a single raw file.")
    parser.add_argument("--force", action="store_true", help="Reprocess even if already classified.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.file:
            raw_path = Path(args.file)
            if not raw_path.is_absolute():
                raw_path = (PROJECT_ROOT / raw_path).resolve()
            result = process_raw_file(raw_path, force=args.force)
            return 0 if result or not args.force else 0
        process_all_unclassified(force=args.force)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
