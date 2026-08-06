"""Phase 2.3 — Pipeline orchestrator: classify new raw captures then auto-link wiki notes.

Usage:
    python pipeline.py          # classify new raw + link new wiki notes
    python pipeline.py --all    # full reprocess (force reclassify + relink)
    python pipeline.py --classify-only   # only classify, skip linking
    python pipeline.py --link-only       # only link, skip classification
"""

from __future__ import annotations

import argparse
import sys
import time

from config import DATA_DIR, EMBEDDINGS_DIR, RAW_DIR, WIKI_DIR

# ---------------------------------------------------------------------------
# Step runners
# ---------------------------------------------------------------------------


def _run_classify(*, force: bool = False) -> tuple[int, int]:
    """Run classification on raw captures. Returns (classified_count, failure_count)."""
    from classify import get_unprocessed_raw, process_raw_file

    raw_files = get_unprocessed_raw(force=force)
    if not raw_files:
        print("  No unclassified raw captures found.")
        return 0, 0

    classified = 0
    failures = 0
    for raw_path in raw_files:
        try:
            result = process_raw_file(raw_path, force=force)
            if result:
                classified += 1
        except Exception as exc:
            failures += 1
            print(f"  Error classifying {raw_path.name}: {exc}", file=sys.stderr)

    return classified, failures


def _run_link() -> int:
    """Run auto-linking on all wiki notes. Returns total new links added."""
    from link import link_all_notes

    return link_all_notes()


# ---------------------------------------------------------------------------
# Summary display
# ---------------------------------------------------------------------------

def _count_raw_captures() -> int:
    """Count actual raw capture files (excluding .gitkeep and .meta.json)."""
    if not RAW_DIR.exists():
        return 0
    return sum(
        1 for f in RAW_DIR.iterdir()
        if f.is_file() and f.name != ".gitkeep" and not f.name.endswith(".meta.json")
    )


def _count_wiki_notes() -> dict[str, int]:
    """Count wiki notes per PARA category."""
    counts: dict[str, int] = {}
    if not WIKI_DIR.exists():
        return counts
    for para_dir in sorted(WIKI_DIR.iterdir()):
        if para_dir.is_dir():
            n = sum(1 for f in para_dir.glob("*.md"))
            if n > 0:
                counts[para_dir.name] = n
    return counts


def _count_embeddings() -> int:
    """Count cached embedding files."""
    if not EMBEDDINGS_DIR.exists():
        return 0
    return sum(1 for f in EMBEDDINGS_DIR.glob("*.npy"))


def _print_separator(char: str = "-", width: int = 60) -> None:
    print(char * width)


def _print_summary(
    classified: int,
    failures: int,
    links_added: int,
    elapsed: float,
    *,
    skipped_classify: bool = False,
    skipped_link: bool = False,
) -> None:
    """Print a final pipeline summary."""
    print()
    _print_separator("=")
    print("  PIPELINE SUMMARY")
    _print_separator("=")

    # Classification results
    if skipped_classify:
        print("  Classification : skipped (--link-only)")
    else:
        print(f"  Classified     : {classified} note(s)")
        if failures:
            print(f"  Failed         : {failures}")

    # Linking results
    if skipped_link:
        print("  Linking        : skipped (--classify-only)")
    else:
        print(f"  Links added    : {links_added}")

    # Corpus stats
    raw_count = _count_raw_captures()
    wiki_counts = _count_wiki_notes()
    total_wiki = sum(wiki_counts.values())
    embed_count = _count_embeddings()

    _print_separator()
    print(f"  Raw captures   : {raw_count}")
    print(f"  Wiki notes     : {total_wiki}")
    if wiki_counts:
        for para, count in wiki_counts.items():
            print(f"    {para:<12} : {count}")
    print(f"  Embeddings     : {embed_count}")
    print(f"  Elapsed        : {elapsed:.1f}s")
    _print_separator("=")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "SecondSelf pipeline: classify raw captures into wiki notes, "
            "then auto-link related notes using embeddings."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Full reprocess: force-reclassify all raw captures and relink all wiki notes.",
    )
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="Only run classification; skip the linking step.",
    )
    parser.add_argument(
        "--link-only",
        action="store_true",
        help="Only run linking; skip the classification step.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    force = args.all

    if args.classify_only and args.link_only:
        print("Error: --classify-only and --link-only are mutually exclusive.", file=sys.stderr)
        return 1

    print()
    _print_separator("=")
    print("  SecondSelf Pipeline")
    _print_separator("=")
    if force:
        print("  Mode: FULL REPROCESS (--all)")
    elif args.classify_only:
        print("  Mode: CLASSIFY ONLY")
    elif args.link_only:
        print("  Mode: LINK ONLY")
    else:
        print("  Mode: incremental (new captures only)")
    print()

    start = time.time()
    classified = 0
    failures = 0
    links_added = 0

    # --- Step 1: Classify ---
    if not args.link_only:
        print("[1/2] Classifying raw captures ...")
        _print_separator()
        try:
            classified, failures = _run_classify(force=force)
        except RuntimeError as exc:
            print(f"  Classification error: {exc}", file=sys.stderr)
            return 1
        print()
    else:
        print("[1/2] Classification skipped (--link-only)")
        print()

    # --- Step 2: Link ---
    if not args.classify_only:
        print("[2/2] Auto-linking wiki notes ...")
        _print_separator()
        try:
            links_added = _run_link()
        except RuntimeError as exc:
            print(f"  Linking error: {exc}", file=sys.stderr)
            return 1
    else:
        print("[2/2] Linking skipped (--classify-only)")

    elapsed = time.time() - start

    _print_summary(
        classified,
        failures,
        links_added,
        elapsed,
        skipped_classify=args.link_only,
        skipped_link=args.classify_only,
    )

    if failures and not classified:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
