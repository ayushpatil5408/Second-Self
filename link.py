"""Phase 2.2 — Auto-Link: embedding-based similarity linking for wiki notes."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import frontmatter
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from config import (
    EMBEDDINGS_DIR,
    EMBEDDING_MODEL,
    MAX_LINKS_PER_NOTE,
    PROJECT_ROOT,
    SIMILARITY_THRESHOLD,
    WIKI_DIR,
)

MIN_EMBED_CHARS = 20
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WikiNoteEntry:
    """In-memory representation of a single wiki note for linking."""

    note_id: str
    path: Path
    slug: str
    para: str
    summary: str
    tags: list[str]
    body: str
    vector: np.ndarray | None = None
    existing_links: list[str] = field(default_factory=list)


@dataclass
class LinkMatch:
    """A similarity match between two notes."""

    note_id: str
    slug: str
    score: float


# ---------------------------------------------------------------------------
# Embedding model (cached singleton)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_embedding_model() -> SentenceTransformer:
    """Load and cache the sentence-transformer model."""
    print(f"Loading embedding model: {EMBEDDING_MODEL} ...")
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load embedding model '{EMBEDDING_MODEL}'. "
            "An internet connection is required on first run to download it."
        ) from exc
    print("Embedding model loaded.")
    return model


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _embed_text(text: str) -> np.ndarray:
    """Encode a single text string into a normalised vector."""
    model = load_embedding_model()
    vector = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(vector, dtype=np.float32)


def embed_note(body: str, *, summary: str = "", tags: list[str] | None = None) -> np.ndarray:
    """Embed the note body; fall back to summary + tags when body is too short."""
    text = body.strip()
    if len(text) < MIN_EMBED_CHARS:
        fallback_parts = [summary.strip()]
        if tags:
            fallback_parts.append(" ".join(tags))
        text = " ".join(p for p in fallback_parts if p).strip()
    if not text:
        text = "untitled"
    return _embed_text(text)


# ---------------------------------------------------------------------------
# Embedding cache (embeddings/{note_id}.npy)
# ---------------------------------------------------------------------------

def _cache_path(note_id: str) -> Path:
    return EMBEDDINGS_DIR / f"{note_id}.npy"


def load_cached_embedding(note_id: str, note_path: Path) -> np.ndarray | None:
    """Return cached vector if the cache file exists and is newer than the note."""
    cache = _cache_path(note_id)
    if not cache.exists():
        return None
    try:
        if note_path.stat().st_mtime > cache.stat().st_mtime:
            return None  # stale
        vec = np.load(cache)
        return np.asarray(vec, dtype=np.float32)
    except Exception:
        return None


def save_cached_embedding(note_id: str, vector: np.ndarray) -> None:
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_cache_path(note_id), vector)


def load_or_compute_embedding(note_id: str, note_path: Path, body: str,
                              *, summary: str = "", tags: list[str] | None = None) -> np.ndarray:
    """Load from cache or compute and cache a fresh embedding."""
    cached = load_cached_embedding(note_id, note_path)
    if cached is not None:
        return cached
    vector = embed_note(body, summary=summary, tags=tags)
    save_cached_embedding(note_id, vector)
    return vector


# ---------------------------------------------------------------------------
# Wiki index builder
# ---------------------------------------------------------------------------

def _extract_slug_from_path(path: Path) -> str:
    return path.stem


def _collect_wiki_notes() -> list[WikiNoteEntry]:
    """Walk wiki/ and parse every .md file into a WikiNoteEntry."""
    entries: list[WikiNoteEntry] = []
    if not WIKI_DIR.exists():
        return entries

    for note_path in sorted(WIKI_DIR.rglob("*.md")):
        try:
            post = frontmatter.load(note_path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

        note_id = str(post.get("id", "")).strip()
        if not note_id:
            continue

        slug = _extract_slug_from_path(note_path)
        para = str(post.get("para", "Resources")).strip()
        summary = str(post.get("summary", "")).strip()
        tags = post.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags]

        existing_links = post.get("links", [])
        if not isinstance(existing_links, list):
            existing_links = []
        existing_links = [str(l) for l in existing_links]

        body = post.content.strip()

        entries.append(WikiNoteEntry(
            note_id=note_id,
            path=note_path,
            slug=slug,
            para=para,
            summary=summary,
            tags=tags,
            body=body,
            existing_links=existing_links,
        ))

    return entries


def build_wiki_index() -> dict[str, WikiNoteEntry]:
    """Build a dict of note_id → WikiNoteEntry with embeddings computed."""
    entries = _collect_wiki_notes()
    if not entries:
        return {}

    print(f"Building wiki index: {len(entries)} note(s) found.")
    index: dict[str, WikiNoteEntry] = {}
    for entry in entries:
        entry.vector = load_or_compute_embedding(
            entry.note_id, entry.path, entry.body,
            summary=entry.summary, tags=entry.tags,
        )
        index[entry.note_id] = entry

    print(f"Wiki index built with {len(index)} note(s).")
    return index


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def find_similar_notes(
    vector: np.ndarray,
    index: dict[str, WikiNoteEntry],
    threshold: float = SIMILARITY_THRESHOLD,
    *,
    exclude_id: str = "",
    max_links: int = MAX_LINKS_PER_NOTE,
) -> list[LinkMatch]:
    """Return the top similar notes above threshold, excluding self."""
    if not index:
        return []

    ids = list(index.keys())
    matrix = np.stack([index[nid].vector for nid in ids])

    query = vector.reshape(1, -1)
    scores = cosine_similarity(query, matrix).flatten()

    matches: list[LinkMatch] = []
    for idx, score in enumerate(scores):
        nid = ids[idx]
        if nid == exclude_id:
            continue
        if score < threshold:
            continue
        matches.append(LinkMatch(
            note_id=nid,
            slug=index[nid].slug,
            score=float(score),
        ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:max_links]


# ---------------------------------------------------------------------------
# Link insertion
# ---------------------------------------------------------------------------

def _existing_wikilinks(body: str) -> set[str]:
    return set(WIKILINK_RE.findall(body))


def insert_links(note_path: Path, matches: list[LinkMatch]) -> None:
    """Update frontmatter links and append [[slug]] wikilinks to the body."""
    if not matches:
        return

    post = frontmatter.load(note_path)

    # --- frontmatter links (deduplicated) ---
    current_links: list[str] = post.get("links", [])
    if not isinstance(current_links, list):
        current_links = []
    current_link_set = {str(l) for l in current_links}

    new_link_ids = [m.note_id for m in matches if m.note_id not in current_link_set]

    # --- body wikilinks (deduplicated) ---
    body = post.content.rstrip()
    existing_slugs = _existing_wikilinks(body)
    new_slugs = [m.slug for m in matches if m.slug not in existing_slugs]

    if not new_link_ids and not new_slugs:
        return  # nothing new to add

    if new_link_ids:
        updated_links = list(current_links) + new_link_ids
        post.metadata["links"] = updated_links

    if new_slugs:
        wikilink_block = "\n".join(f"[[{s}]]" for s in new_slugs)
        if "## Related Notes" in body:
            body = body.rstrip() + "\n" + wikilink_block + "\n"
        elif body.strip():
            body = body.rstrip() + "\n\n## Related Notes\n\n" + wikilink_block + "\n"
        else:
            body = "## Related Notes\n\n" + wikilink_block + "\n"
        post.content = body

    note_path.write_text(frontmatter.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def link_single_note(note_path: Path, index: dict[str, WikiNoteEntry] | None = None) -> int:
    """Link a single wiki note against the full index. Returns link count added."""
    note_path = note_path.resolve()
    if not note_path.is_file():
        print(f"Note not found: {note_path}", file=sys.stderr)
        return 0

    if index is None:
        index = build_wiki_index()
    if not index:
        print("No wiki notes found in index.")
        return 0

    # Find this note in the index
    entry: WikiNoteEntry | None = None
    for e in index.values():
        if e.path.resolve() == note_path:
            entry = e
            break

    if entry is None:
        print(f"Note not found in wiki index: {note_path}", file=sys.stderr)
        return 0

    if entry.vector is None:
        entry.vector = load_or_compute_embedding(
            entry.note_id, entry.path, entry.body,
            summary=entry.summary, tags=entry.tags,
        )

    matches = find_similar_notes(entry.vector, index, exclude_id=entry.note_id)
    if not matches:
        print(f"No similar notes found for: {entry.slug}")
        return 0

    insert_links(entry.path, matches)
    print(f"Linked {entry.slug} -> {len(matches)} related note(s): "
          f"{', '.join(m.slug for m in matches)}")
    return len(matches)


def link_all_notes() -> int:
    """Process every wiki note and insert links. Returns total links added."""
    index = build_wiki_index()
    if not index:
        print("No wiki notes found. Run classify.py first.")
        return 0

    if len(index) < 2:
        print("Only 1 wiki note found — need at least 2 to create links.")
        return 0

    total_links = 0
    for entry in index.values():
        matches = find_similar_notes(entry.vector, index, exclude_id=entry.note_id)
        # Filter out already-existing links for idempotency
        existing_set = set(entry.existing_links)
        new_matches = [m for m in matches if m.note_id not in existing_set]
        if new_matches:
            insert_links(entry.path, new_matches)
            print(f"  {entry.slug} -> +{len(new_matches)} link(s): "
                  f"{', '.join(m.slug for m in new_matches)}")
            total_links += len(new_matches)

    print(f"\nLinking complete: {total_links} new link(s) added across {len(index)} note(s).")
    return total_links


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-link wiki notes using sentence-transformer embeddings."
    )
    parser.add_argument(
        "--note", "-n",
        help="Path to a single wiki note to link (e.g. wiki/Projects/foo.md).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.note:
            note_path = Path(args.note)
            if not note_path.is_absolute():
                note_path = (PROJECT_ROOT / note_path).resolve()
            link_single_note(note_path)
        else:
            link_all_notes()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
