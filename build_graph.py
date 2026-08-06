"""Phase 3.1 — Graph builder: export wiki notes as nodes + edges to graph.json.

Reads every wiki note's frontmatter and body, builds a node per note and an
edge per link (from frontmatter ``links:`` and ``[[wikilinks]]`` in the body),
then writes ``data/graph.json``.

Usage:
    python build_graph.py
    python build_graph.py --output data/graph.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import numpy as np

from config import EMBEDDINGS_DIR, GRAPH_PATH, PROJECT_ROOT, WIKI_DIR

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
CONTENT_PREVIEW_LEN = 200


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WikiNode:
    """A single wiki note represented as a graph node."""

    id: str
    label: str
    para: str
    tags: list[str]
    summary: str
    content_preview: str
    path: str


@dataclass
class GraphEdge:
    """A directed edge between two notes."""

    source: str
    target: str
    weight: float
    type: str = "semantic_similarity"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _slug_to_note_id(wiki_dir: Path, slug: str) -> str | None:
    """Resolve a wikilink slug to a note ID by scanning wiki files."""
    for note_path in wiki_dir.rglob("*.md"):
        if note_path.stem == slug:
            try:
                post = frontmatter.load(note_path)
                note_id = str(post.get("id", "")).strip()
                if note_id:
                    return note_id
            except (OSError, UnicodeDecodeError, ValueError):
                continue
    return None


def extract_wikilinks(body: str) -> list[str]:
    """Return all ``[[slug]]`` references found in the markdown body."""
    return WIKILINK_RE.findall(body)


def _make_label(slug: str) -> str:
    """Convert a kebab-case slug into a human-readable label."""
    return slug.replace("-", " ").title()


def _make_content_preview(body: str) -> str:
    """First ~200 characters of the body, collapsed to single line."""
    text = " ".join(body.split())
    if len(text) <= CONTENT_PREVIEW_LEN:
        return text
    return text[: CONTENT_PREVIEW_LEN - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Node / edge builders
# ---------------------------------------------------------------------------

def parse_wiki_note(note_path: Path) -> WikiNode | None:
    """Read a single wiki note and return a WikiNode, or None on failure."""
    try:
        post = frontmatter.load(note_path)
    except (OSError, UnicodeDecodeError, ValueError):
        return None

    note_id = str(post.get("id", "")).strip()
    if not note_id:
        return None

    slug = note_path.stem
    para = str(post.get("para", "Resources")).strip()
    tags = post.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags]

    summary = str(post.get("summary", "")).strip()
    body = post.content.strip()

    return WikiNode(
        id=note_id,
        label=_make_label(slug),
        para=para,
        tags=tags,
        summary=summary,
        content_preview=_make_content_preview(body),
        path=str(note_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    )


def build_nodes(wiki_dir: Path) -> dict[str, WikiNode]:
    """Walk wiki/ and return a dict of note_id -> WikiNode."""
    nodes: dict[str, WikiNode] = {}
    if not wiki_dir.exists():
        return nodes

    for note_path in sorted(wiki_dir.rglob("*.md")):
        node = parse_wiki_note(note_path)
        if node:
            nodes[node.id] = node

    return nodes


def _load_embedding(note_id: str) -> np.ndarray | None:
    """Load a cached embedding vector for the given note ID."""
    npy_path = EMBEDDINGS_DIR / f"{note_id}.npy"
    if not npy_path.exists():
        return None
    try:
        return np.asarray(np.load(npy_path), dtype=np.float32)
    except Exception:
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def build_edges(nodes: dict[str, WikiNode]) -> list[GraphEdge]:
    """Build edges from frontmatter ``links:`` arrays and body ``[[wikilinks]]``.

    Edge weights are cosine similarity scores from cached embeddings when
    available; otherwise a default weight of 1.0 is used.
    """
    seen: set[tuple[str, str]] = set()
    edges: list[GraphEdge] = []

    # Pre-load all available embeddings for weight computation
    embeddings: dict[str, np.ndarray] = {}
    for nid in nodes:
        vec = _load_embedding(nid)
        if vec is not None:
            embeddings[nid] = vec

    for nid, node in nodes.items():
        note_path = PROJECT_ROOT / node.path
        try:
            post = frontmatter.load(note_path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

        target_ids: set[str] = set()

        # From frontmatter links (these are note IDs)
        fm_links = post.get("links", [])
        if isinstance(fm_links, list):
            for link_id in fm_links:
                link_id = str(link_id).strip()
                if link_id and link_id in nodes and link_id != nid:
                    target_ids.add(link_id)

        # From body wikilinks (these are slugs, resolve to IDs)
        body = post.content or ""
        for slug in extract_wikilinks(body):
            resolved = _slug_to_note_id(WIKI_DIR, slug)
            if resolved and resolved in nodes and resolved != nid:
                target_ids.add(resolved)

        # Create edges
        for target_id in target_ids:
            pair = (nid, target_id)
            if pair in seen:
                continue
            seen.add(pair)

            # Compute weight from embeddings if both vectors exist
            weight = 1.0
            if nid in embeddings and target_id in embeddings:
                weight = round(_cosine_similarity(embeddings[nid], embeddings[target_id]), 4)

            edges.append(GraphEdge(
                source=nid,
                target=target_id,
                weight=weight,
            ))

    return edges


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(
    nodes: dict[str, WikiNode],
    edges: list[GraphEdge],
    output_path: Path,
) -> Path:
    """Write the graph as JSON to *output_path* and return the path."""
    graph = {
        "nodes": [asdict(n) for n in nodes.values()],
        "edges": [asdict(e) for e in edges],
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "SecondSelf build_graph.py",
        },
    }

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_graph(output_path: Path | None = None) -> tuple[int, int]:
    """Build the full graph and export JSON.

    Returns:
        (node_count, edge_count)
    """
    if output_path is None:
        output_path = GRAPH_PATH

    nodes = build_nodes(WIKI_DIR)
    if not nodes:
        print("No wiki notes found. Run the pipeline first.")
        return 0, 0

    edges = build_edges(nodes)

    written = export_json(nodes, edges, output_path)

    print(f"Graph built: {len(nodes)} node(s), {len(edges)} edge(s)")
    print(f"  -> {written.relative_to(PROJECT_ROOT)}")
    return len(nodes), len(edges)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build graph.json from wiki notes (nodes + edges)."
    )
    parser.add_argument(
        "--output", "-o",
        help=f"Output path for graph JSON (default: {GRAPH_PATH}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output) if args.output else GRAPH_PATH
    if not output.is_absolute():
        output = (PROJECT_ROOT / output).resolve()

    node_count, edge_count = build_graph(output)
    if node_count == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
