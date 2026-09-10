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
# Groq client & API key handling
# ---------------------------------------------------------------------------

DUMMY_API_KEYS = {
    "your-groq-api-key-here",
    "gsk_xxxxxxxxxxxxxxxxxxxx",
    "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
}


def resolve_groq_api_key(api_key: str | None = None) -> str | None:
    """Resolve Groq API key from parameter, Streamlit session state, env, or secrets."""
    if api_key and api_key.strip() and api_key.strip() not in DUMMY_API_KEYS:
        return api_key.strip()

    # Check Streamlit session state only if inside an active Streamlit runner
    if "streamlit" in sys.modules:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                session_key = st.session_state.get("groq_api_key")
                if session_key and session_key.strip() and session_key.strip() not in DUMMY_API_KEYS:
                    return session_key.strip()
                secret_key = st.secrets.get("GROQ_API_KEY", "").strip()
                if secret_key and secret_key not in DUMMY_API_KEYS:
                    return secret_key
        except Exception:
            pass

    load_dotenv()
    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key and env_key not in DUMMY_API_KEYS:
        return env_key

    return None


def validate_groq_api_key(api_key: str) -> tuple[bool, str]:
    """Test if a Groq API key is valid by querying the Groq API."""
    key = api_key.strip() if api_key else ""
    if not key or key in DUMMY_API_KEYS:
        return False, "API key is empty or a placeholder."
    try:
        client = Groq(api_key=key, timeout=10.0)
        client.models.list()
        return True, "API key is valid."
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "invalid_api_key" in msg.lower() or "authentication" in msg.lower():
            return False, "Invalid Groq API key (Authentication failed). Check console.groq.com/keys."
        return False, f"Groq error: {msg}"


def _get_groq_client(api_key: str | None = None) -> Groq:
    """Initialize and return a Groq client with resolved API key."""
    resolved_key = resolve_groq_api_key(api_key)
    if not resolved_key:
        error_msg = (
            "GROQ_API_KEY is not set or is invalid.\n"
            "Options:\n"
            "1. Local: Add GROQ_API_KEY to .env file\n"
            "2. Streamlit UI: Enter GROQ_API_KEY in the sidebar settings\n"
            "3. Streamlit Cloud: Add GROQ_API_KEY in Secrets tab\n"
            "4. Environment: Set GROQ_API_KEY environment variable\n"
            "Get a free key at: https://console.groq.com/keys"
        )
        raise RuntimeError(error_msg)

    return Groq(api_key=resolved_key, timeout=15.0)


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
# ---------------------------------------------------------------------------
# Fallback Extractive Synthesis
# ---------------------------------------------------------------------------

def _generate_extractive_fallback(
    question: str,
    retrieved: list[RetrievedNote],
    reason: str = "",
) -> str:
    """Generate an informative, synthesized answer from retrieved notes when Groq LLM is unavailable."""
    lines = []
    if reason:
        lines.append(f"> ⚠️ **Groq AI Notice**: LLM synthesis unavailable ({reason}).")
        lines.append("> Retrieved relevant knowledge directly from your second brain:")
        lines.append("")

    lines.append(f"**Found {len(retrieved)} relevant note(s) for:** *\"{question}\"*")
    lines.append("")

    for i, note in enumerate(retrieved, 1):
        clean_title = note.slug.replace("-", " ").title()
        lines.append(f"### {i}. {clean_title} `[{note.para}]`")
        if note.summary and note.summary.strip():
            lines.append(f"**Summary:** {note.summary.strip()}\n")

        # Extract useful content excerpt
        body_snippet = note.body.strip()
        body_lines = [
            line.strip()
            for line in body_snippet.splitlines()
            if line.strip() and not line.startswith("---") and not line.startswith("#") and not line.startswith("created:") and not line.startswith("para:")
        ]
        excerpt = " ".join(body_lines)
        if len(excerpt) > 280:
            excerpt = excerpt[:277] + "..."
        if excerpt and excerpt != note.summary.strip():
            lines.append(f"> *Excerpt:* {excerpt}\n")

    lines.append("---")
    lines.append("💡 *Tip: To enable conversational AI answers, configure a valid Groq API key in the sidebar API Settings or `.env` file ([console.groq.com/keys](https://console.groq.com/keys)).*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def synthesize_answer(
    system_prompt: str,
    user_prompt: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Call Groq LLM to synthesize an answer from the RAG prompt."""
    target_model = model or os.environ.get("LLM_MODEL") or LLM_MODEL
    client = _get_groq_client(api_key=api_key)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            err_str = str(exc)
            # Fail fast on auth error or missing model
            if status == 401 or "invalid_api_key" in err_str.lower() or "authentication" in err_str.lower():
                raise RuntimeError("Invalid Groq API key. Please check your GROQ_API_KEY in the sidebar or .env file.") from exc
            if status == 404 or "model_not_found" in err_str.lower():
                raise RuntimeError(f"Groq model '{target_model}' not found.") from exc
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
    api_key: str | None = None,
    model: str | None = None,
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

    try:
        system_prompt, user_prompt = build_rag_prompt(question, retrieved)
        answer = synthesize_answer(system_prompt, user_prompt, api_key=api_key, model=model)
        return AskResult(answer=answer, sources=retrieved)
    except Exception as exc:
        err_msg = str(exc)
        if "Invalid Groq API key" in err_msg or "GROQ_API_KEY is not set" in err_msg or "Authentication" in err_msg:
            reason = "Invalid or unconfigured Groq API Key"
        else:
            reason = f"Groq API error ({err_msg[:60]})"
        fallback_answer = _generate_extractive_fallback(question, retrieved, reason=reason)
        return AskResult(answer=fallback_answer, sources=retrieved)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _safe_print(text: str = "") -> None:
    """Safely print text handling Windows console encoding fallbacks."""
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii")
        print(safe_text)


def _print_result(result: AskResult, *, show_scores: bool = False) -> None:
    """Pretty-print an AskResult to stdout."""
    _safe_print()
    _safe_print("=" * 60)
    _safe_print("  Answer")
    _safe_print("=" * 60)
    _safe_print(result.answer)

    if result.sources:
        _safe_print()
        _safe_print("-" * 60)
        _safe_print("  Sources")
        _safe_print("-" * 60)
        for i, src in enumerate(result.sources, 1):
            score_str = f"  (score: {src.score:.3f})" if show_scores else ""
            _safe_print(f"  {i}. {src.slug} [{src.para}]{score_str}")
            _safe_print(f"     {src.path}")

    _safe_print("=" * 60)
    _safe_print()


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
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
