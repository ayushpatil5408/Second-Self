"""Shared configuration for SecondSelf."""

from __future__ import annotations

import base64
import os
import sys
import typing
from pathlib import Path

if not hasattr(typing, "TypeGuard"):
    try:
        import typing_extensions
        typing.TypeGuard = typing_extensions.TypeGuard
    except ImportError:
        pass

from dotenv import load_dotenv

load_dotenv()

MIN_PYTHON_VERSION = (3, 9)

PROJECT_ROOT = Path(__file__).resolve().parent

RAW_DIR = PROJECT_ROOT / "raw"
WIKI_DIR = PROJECT_ROOT / "wiki"
DATA_DIR = PROJECT_ROOT / "data"
EMBEDDINGS_DIR = PROJECT_ROOT / "embeddings"
GRAPH_PATH = DATA_DIR / "graph.json"

SIMILARITY_THRESHOLD = 0.45
MAX_LINKS_PER_NOTE = 5
RAG_TOP_K = 5
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_LLM_MODEL = "llama-3.1-8b-instant"
LLM_MODEL = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)

# API and OAuth credentials resolved from environment or Streamlit secrets
DEFAULT_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Default Google OAuth credentials
DEFAULT_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DEFAULT_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DEFAULT_GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "https://second-self-monster.streamlit.app/")





def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        major, minor = MIN_PYTHON_VERSION
        raise RuntimeError(
            f"SecondSelf requires Python {major}.{minor}+; "
            f"found {sys.version_info.major}.{sys.version_info.minor}."
        )


def _validate_config() -> None:
    if not 0.0 <= SIMILARITY_THRESHOLD <= 1.0:
        raise ValueError("SIMILARITY_THRESHOLD must be between 0.0 and 1.0.")
    if MAX_LINKS_PER_NOTE < 1:
        raise ValueError("MAX_LINKS_PER_NOTE must be at least 1.")
    if RAG_TOP_K < 1:
        raise ValueError("RAG_TOP_K must be at least 1.")


PARA_CATEGORIES = ("Projects", "Areas", "Resources", "Archives")


def ensure_dirs() -> None:
    """Create required project directories if they do not exist."""
    for directory in (RAW_DIR, WIKI_DIR, DATA_DIR, EMBEDDINGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    for category in PARA_CATEGORIES:
        (WIKI_DIR / category).mkdir(parents=True, exist_ok=True)


def get_user_workspace(user_id: str | None = None) -> dict[str, Path]:
    """Get isolated workspace paths for a user (or global defaults if user_id is None)."""
    import re
    if not user_id:
        return {
            "user_root": PROJECT_ROOT,
            "raw_dir": RAW_DIR,
            "wiki_dir": WIKI_DIR,
            "embeddings_dir": EMBEDDINGS_DIR,
            "graph_path": GRAPH_PATH,
        }

    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(user_id).strip())
    user_root = DATA_DIR / "users" / safe_id
    raw_dir = user_root / "raw"
    wiki_dir = user_root / "wiki"
    embeddings_dir = user_root / "embeddings"
    graph_path = user_root / "graph.json"

    for d in (raw_dir, wiki_dir, embeddings_dir):
        d.mkdir(parents=True, exist_ok=True)
    for category in PARA_CATEGORIES:
        (wiki_dir / category).mkdir(parents=True, exist_ok=True)

    return {
        "user_root": user_root,
        "raw_dir": raw_dir,
        "wiki_dir": wiki_dir,
        "embeddings_dir": embeddings_dir,
        "graph_path": graph_path,
    }


def init_user_workspace(user_id: str, user_name: str = "") -> None:
    """Ensure user workspace exists and has a starter welcome note if brand new."""
    from datetime import datetime
    ws = get_user_workspace(user_id)
    wiki_dir = ws["wiki_dir"]

    # Check if user already has any notes
    has_notes = any(wiki_dir.rglob("*.md"))
    if not has_notes:
        display_name = user_name or "Friend"
        welcome_file = wiki_dir / "Projects" / "welcome-to-second-self.md"
        content = f"""---
id: "welcome_{user_id[:8]}"
title: "Welcome to SecondSelf"
para: "Projects"
tags: ["welcome", "second-brain"]
summary: "Welcome to your personal private AI Second Brain. Capture thoughts, notes, and media files."
created: "{datetime.now().isoformat()}"
links: []
---

# Welcome to SecondSelf, {display_name}!

This is your private, personal AI Second Brain. Everything you store here is completely private to your account.

### How to use your Second Brain:
- **Sidebar Capture**: Use the sidebar on the left to capture quick notes, web links, or upload media (images, PDFs, documents, audio).
- **Automatic Analysis**: When you capture media or notes, the AI analyzes the content and categorizes it into the PARA structure (Projects, Areas, Resources, Archives).
- **Natural Language Search**: Type any question in the search bar to query your knowledge base and view matched images, documents, and media.
"""
        welcome_file.write_text(content, encoding="utf-8")
        try:
            from build_graph import build_graph
            build_graph(output_path=ws["graph_path"], wiki_dir=wiki_dir)
        except Exception:
            pass


_check_python_version()
_validate_config()
ensure_dirs()
