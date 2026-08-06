"""Diagnostic viewer for cached note embeddings.

Reads `.npy` vectors from `embeddings/` (and optionally `data/embeddings.pkl`)
and displays a summary table with cosine similarity heatmap across all notes.

Usage:
    python view_embeddings.py                  # show all cached embeddings
    python view_embeddings.py --top 5          # show top-5 most similar pairs
    python view_embeddings.py --note 6f874ddc  # inspect a single note vector
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import frontmatter
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from config import DATA_DIR, EMBEDDINGS_DIR, PROJECT_ROOT, WIKI_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wiki_note_by_id(note_id: str) -> dict[str, str] | None:
    """Find a wiki note's metadata by its capture id."""
    if not WIKI_DIR.exists():
        return None
    for note_path in WIKI_DIR.rglob("*.md"):
        try:
            post = frontmatter.load(note_path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if str(post.get("id", "")) == note_id:
            return {
                "id": note_id,
                "slug": note_path.stem,
                "para": str(post.get("para", "")),
                "summary": str(post.get("summary", "")),
                "tags": ", ".join(str(t) for t in post.get("tags", [])),
                "path": str(note_path.relative_to(PROJECT_ROOT)),
            }
    return None


def _load_npy_embeddings() -> dict[str, np.ndarray]:
    """Load all .npy vectors from the embeddings/ directory."""
    vectors: dict[str, np.ndarray] = {}
    if not EMBEDDINGS_DIR.exists():
        return vectors
    for npy_path in sorted(EMBEDDINGS_DIR.glob("*.npy")):
        try:
            vec = np.load(npy_path)
            vectors[npy_path.stem] = np.asarray(vec, dtype=np.float32)
        except Exception as exc:
            print(f"  Warning: could not load {npy_path.name}: {exc}", file=sys.stderr)
    return vectors


def _load_pkl_embeddings(pkl_path: Path) -> dict[str, np.ndarray]:
    """Load embeddings from a pickle file (data/embeddings.pkl)."""
    if not pkl_path.exists():
        return {}
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)
    # Accept dict[str, ndarray] or dict[str, list]
    vectors: dict[str, np.ndarray] = {}
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, np.ndarray):
                vectors[str(key)] = val.astype(np.float32)
            elif isinstance(val, (list, tuple)):
                vectors[str(key)] = np.array(val, dtype=np.float32)
    return vectors


def load_all_embeddings() -> dict[str, np.ndarray]:
    """Merge .npy cache and optional data/embeddings.pkl."""
    vectors = _load_npy_embeddings()

    pkl_path = DATA_DIR / "embeddings.pkl"
    if pkl_path.exists():
        pkl_vectors = _load_pkl_embeddings(pkl_path)
        for nid, vec in pkl_vectors.items():
            if nid not in vectors:
                vectors[nid] = vec

    return vectors


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------

def _print_separator(char: str = "-", width: int = 90) -> None:
    print(char * width)


def show_all_embeddings(vectors: dict[str, np.ndarray], *, top_n: int = 10) -> None:
    """Print a summary table of all cached embeddings."""
    if not vectors:
        print("No embeddings found.")
        print(f"  Searched: {EMBEDDINGS_DIR}/ (*.npy) and {DATA_DIR}/embeddings.pkl")
        print("  Run `python link.py` first to generate embeddings.")
        return

    print(f"\n{'EMBEDDING CACHE SUMMARY':^90}")
    _print_separator("=")
    print(f"  Total vectors : {len(vectors)}")
    first_vec = next(iter(vectors.values()))
    print(f"  Vector dim    : {first_vec.shape[0]}")
    print(f"  Sources       : {EMBEDDINGS_DIR}/ (*.npy)")
    pkl_path = DATA_DIR / "embeddings.pkl"
    if pkl_path.exists():
        print(f"                : {pkl_path}")
    _print_separator()

    # Per-note table
    header = f"  {'ID':<12} {'PARA':<12} {'Slug':<40} {'||v||':>8}"
    print(header)
    _print_separator()

    for note_id in sorted(vectors):
        vec = vectors[note_id]
        norm = float(np.linalg.norm(vec))
        meta = _wiki_note_by_id(note_id)
        if meta:
            slug = meta["slug"][:38]
            para = meta["para"][:10]
        else:
            slug = "(unknown)"
            para = "?"
        print(f"  {note_id:<12} {para:<12} {slug:<40} {norm:>8.4f}")

    _print_separator()

    # Similarity pairs
    if len(vectors) >= 2:
        _print_top_similar(vectors, top_n=top_n)
    else:
        print("  Need at least 2 vectors to compute similarity.")

    print()


def _print_top_similar(vectors: dict[str, np.ndarray], *, top_n: int = 10) -> None:
    """Print the top-N most similar note pairs."""
    ids = sorted(vectors)
    matrix = np.stack([vectors[nid] for nid in ids])
    sim_matrix = cosine_similarity(matrix)

    pairs: list[tuple[str, str, float]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pairs.append((ids[i], ids[j], float(sim_matrix[i, j])))

    pairs.sort(key=lambda p: p[2], reverse=True)

    print(f"\n  TOP {min(top_n, len(pairs))} MOST SIMILAR PAIRS:")
    _print_separator()
    print(f"  {'Note A':<14} {'Note B':<14} {'Score':>7}   {'A Slug':<24} {'B Slug':<24}")
    _print_separator()

    for a_id, b_id, score in pairs[:top_n]:
        a_meta = _wiki_note_by_id(a_id)
        b_meta = _wiki_note_by_id(b_id)
        a_slug = (a_meta["slug"][:22] if a_meta else a_id)
        b_slug = (b_meta["slug"][:22] if b_meta else b_id)
        marker = " *" if score >= 0.75 else ""
        print(f"  {a_id:<14} {b_id:<14} {score:>7.4f}   {a_slug:<24} {b_slug:<24}{marker}")

    _print_separator()
    print("  * = above SIMILARITY_THRESHOLD (0.75)")


def show_single_note(vectors: dict[str, np.ndarray], note_id: str) -> None:
    """Display detailed info for a single note's embedding."""
    if note_id not in vectors:
        print(f"No embedding found for id: {note_id}")
        available = sorted(vectors.keys())
        if available:
            print(f"Available IDs: {', '.join(available)}")
        return

    vec = vectors[note_id]
    meta = _wiki_note_by_id(note_id)

    print(f"\n{'EMBEDDING DETAIL':^90}")
    _print_separator("=")
    print(f"  ID       : {note_id}")
    if meta:
        print(f"  Slug     : {meta['slug']}")
        print(f"  PARA     : {meta['para']}")
        print(f"  Summary  : {meta['summary']}")
        print(f"  Tags     : {meta['tags']}")
        print(f"  Path     : {meta['path']}")
    else:
        print("  (wiki note not found for this ID)")
    print(f"  Vector   : shape={vec.shape}, dtype={vec.dtype}")
    print(f"  Norm     : {float(np.linalg.norm(vec)):.6f}")
    print(f"  Mean     : {float(vec.mean()):.6f}")
    print(f"  Std      : {float(vec.std()):.6f}")
    print(f"  Min      : {float(vec.min()):.6f}")
    print(f"  Max      : {float(vec.max()):.6f}")

    # Top-5 most similar from cache
    if len(vectors) >= 2:
        other_ids = [nid for nid in sorted(vectors) if nid != note_id]
        if other_ids:
            other_matrix = np.stack([vectors[nid] for nid in other_ids])
            query = vec.reshape(1, -1)
            scores = cosine_similarity(query, other_matrix).flatten()

            ranked = sorted(zip(other_ids, scores), key=lambda x: x[1], reverse=True)
            print(f"\n  Top similar notes:")
            for other_id, score in ranked[:5]:
                other_meta = _wiki_note_by_id(other_id)
                other_slug = other_meta["slug"] if other_meta else other_id
                print(f"    {other_id}  {score:.4f}  {other_slug}")

    # Show first/last 10 values
    _print_separator()
    preview_n = min(10, len(vec))
    print(f"  First {preview_n} values: {vec[:preview_n].tolist()}")
    if len(vec) > preview_n:
        print(f"  Last {preview_n} values:  {vec[-preview_n:].tolist()}")
    _print_separator()
    print()


def show_similarity_heatmap(vectors: dict[str, np.ndarray]) -> None:
    """Print a text-based similarity matrix for all notes."""
    if len(vectors) < 2:
        return

    ids = sorted(vectors)
    matrix = np.stack([vectors[nid] for nid in ids])
    sim_matrix = cosine_similarity(matrix)

    print(f"\n{'COSINE SIMILARITY MATRIX':^90}")
    _print_separator("=")

    # Column header (short IDs)
    short = [nid[:6] for nid in ids]
    header = "         " + " ".join(f"{s:>7}" for s in short)
    print(header)

    for i, nid in enumerate(ids):
        row_label = nid[:8]
        cells = []
        for j in range(len(ids)):
            val = sim_matrix[i, j]
            cells.append(f"{val:>7.3f}")
        print(f"  {row_label:<8} {' '.join(cells)}")

    _print_separator()
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="View cached note embeddings and similarity scores."
    )
    parser.add_argument(
        "--note", "-n",
        help="Inspect a single note's embedding by its capture ID (e.g. 6f874ddc).",
    )
    parser.add_argument(
        "--top", "-t", type=int, default=10,
        help="Number of top similar pairs to display (default: 10).",
    )
    parser.add_argument(
        "--matrix", "-m", action="store_true",
        help="Print full cosine similarity matrix.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vectors = load_all_embeddings()

    if not vectors:
        print("No embeddings found. Run `python link.py` first to generate embeddings.")
        return 0

    if args.note:
        show_single_note(vectors, args.note)
    elif args.matrix:
        show_similarity_heatmap(vectors)
    else:
        show_all_embeddings(vectors, top_n=args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
