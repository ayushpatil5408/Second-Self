"""Shared configuration for SecondSelf."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MIN_PYTHON_VERSION = (3, 10)

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


_check_python_version()
_validate_config()
ensure_dirs()
