"""Phase 4.1 — RAG query engine: ask questions over your personal wiki notes."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from groq import Groq
from sklearn.metrics.pairwise import cosine_similarity

from config import LLM_MODEL, PROJECT_ROOT, RAG_TOP_K, WIKI_DIR
from link import (
    WikiNoteEntry,
    _embed_text,
    build_wiki_index,
    load_embedding_model,
)

MAX_RAG_CHARS = 6000
NO_ANSWER_MSG = (
    "I don't have enough information in your notes to answer that. "
    "Try capturing more content on this topic and re-running the pipeline."
)

RAG_SYSTEM_PROMPT = (
    "You are a personal knowledge assistant. Answer the user's question "
    "using ONLY the personal notes provided below. If the notes do not "
    "contain enough information, say so clearly. Cite note titles when "
    "relevant. Do not invent facts."
)

RAG_USER_TEMPLATE = """--- NOTES ---
{notes_block}
--- END ---

Question: {question}"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RetrievedNote:
    """A wiki note retrieved for RAG context."""

    note_id: str
    slug: str
    para: str
    summary: str
    body: str
    score: float
    path: str


@dataclass
class AskResult:
    """Result of an ask() call: synthesized answer plus source notes."""

    answer: str
    sources: list[RetrievedNote] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

def _get_groq_client() -> Groq:
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    # Fallback: Streamlit Community Cloud injects secrets via st.secrets,
    # not via environment variables.  Check there if the env var is absent.
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GROQ_API_KEY")
        except Exception:
            pass
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to .env (see .env.example).")
    return Groq(api_key=api_key)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve(
    question: str,
    index: dict[str, WikiNoteEntry],
    top_k: int = RAG_TOP_K,
) -> list[RetrievedNote]:
    """Embed the question and return the top-k most similar wiki notes."""
    if not index:
        return []

    # Ensure the embedding model is loaded (also warms it for later calls)
    load_embedding_model()

    q_vector = _embed_text(question)

    ids = list(index.keys())
    matrix = np.stack([index[nid].vector for nid in ids])

    query = q_vector.reshape(1, -1)
    scores = cosine_similarity(query, matrix).flatten()

    ranked = sorted(
        zip(ids, scores),
        key=lambda pair: pair[1],
        reverse=True,
    )[:top_k]

    results: list[RetrievedNote] = []
    for nid, score in ranked:
        entry = index[nid]
        results.append(RetrievedNote(
            note_id=nid,
            slug=entry.slug,
            para=entry.para,
            summary=entry.summary,
            body=entry.body,
            score=float(score),
            path=str(entry.path.relative_to(PROJECT_ROOT)),
        ))

    return results


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _format_note_for_prompt(note: RetrievedNote) -> str:
    """Format a single retrieved note for inclusion in the RAG prompt."""
    header = f"{note.slug} [{note.para}]"
    text = note.body.strip()
    if len(text) > MAX_RAG_CHARS:
        text = text[:MAX_RAG_CHARS] + "\n[truncated]"
    return f"{header}: {text}"


def build_rag_prompt(question: str, retrieved: list[RetrievedNote]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the RAG LLM call."""
    if not retrieved:
        notes_block = "(no relevant notes found)"
    else:
        notes_block = "\n\n".join(_format_note_for_prompt(n) for n in retrieved)

    user_prompt = RAG_USER_TEMPLATE.format(notes_block=notes_block, question=question)
    return RAG_SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def synthesize_answer(system_prompt: str, user_prompt: str) -> str:
    """Call Groq LLM to synthesize an answer from the RAG prompt."""
    client = _get_groq_client()
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 429 and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("Groq API call failed after retries.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def ask(
    question: str,
    top_k: int = RAG_TOP_K,
    index: dict[str, WikiNoteEntry] | None = None,
) -> AskResult:
    """Full RAG pipeline: retrieve → build prompt → synthesize answer."""
    question = question.strip()
    if not question:
        return AskResult(answer="Please provide a question.", sources=[])

    if index is None:
        index = build_wiki_index()

    if not index:
        return AskResult(
            answer=(
                "No wiki notes found. Run `python pipeline.py` first to "
                "classify and link your captures."
            ),
            sources=[],
        )

    retrieved = retrieve(question, index, top_k=top_k)

    if not retrieved:
        return AskResult(answer=NO_ANSWER_MSG, sources=[])

    system_prompt, user_prompt = build_rag_prompt(question, retrieved)
    answer = synthesize_answer(system_prompt, user_prompt)

    return AskResult(answer=answer, sources=retrieved)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_result(result: AskResult, *, show_scores: bool = False) -> None:
    """Pretty-print an AskResult to stdout."""
    print()
    print("=" * 60)
    print("  Answer")
    print("=" * 60)
    print(result.answer)

    if result.sources:
        print()
        print("-" * 60)
        print("  Sources")
        print("-" * 60)
        for i, src in enumerate(result.sources, 1):
            score_str = f"  (score: {src.score:.3f})" if show_scores else ""
            print(f"  {i}. {src.slug} [{src.para}]{score_str}")
            print(f"     {src.path}")

    print("=" * 60)
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask a question over your personal wiki notes (RAG)."
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="The question to ask about your notes.",
    )
    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=RAG_TOP_K,
        help=f"Number of notes to retrieve (default: {RAG_TOP_K}).",
    )
    parser.add_argument(
        "--scores", "-s",
        action="store_true",
        help="Show similarity scores next to source notes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.question:
        print("Usage: python ask.py \"your question here\"", file=sys.stderr)
        print("       python ask.py --top-k 3 \"your question\"", file=sys.stderr)
        return 1

    try:
        result = ask(args.question, top_k=args.top_k)
        _print_result(result, show_scores=args.scores)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
