"""Phase 4.2 — Streamlit app: SecondSelf knowledge graph + RAG ask bar."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from config import GRAPH_PATH, PROJECT_ROOT, RAG_TOP_K

# ---------------------------------------------------------------------------
# Page configuration (must be the first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SecondSelf",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARA_COLORS = {
    "Projects":  "#4A90D9",
    "Areas":     "#50C878",
    "Resources": "#F5A623",
    "Archives":  "#9B9B9B",
}

GRAPH_HEIGHT = 640

# ---------------------------------------------------------------------------
# Graph HTML template (embedded in Streamlit via components.v1.html)
# Derived from graph_component.html — sidebar removed (Streamlit provides one).
# ---------------------------------------------------------------------------

_GRAPH_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0E1117;
    color: #FAFAFA;
    overflow: hidden;
    height: 100vh;
  }}
  #graph {{ width: 100%; height: 100vh; background: #0E1117; }}
  @keyframes pulse {{
    0%   {{ box-shadow: 0 0 0 0 rgba(74, 144, 217, 0.4); }}
    70%  {{ box-shadow: 0 0 0 10px rgba(74, 144, 217, 0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(74, 144, 217, 0); }}
  }}
</style>
</head>
<body>
<div id="graph"></div>
<script>
var GRAPH_DATA = __GRAPH_JSON__;

var PARA_COLORS = {
  "Projects":  "#4A90D9",
  "Areas":     "#50C878",
  "Resources": "#F5A623",
  "Archives":  "#9B9B9B"
};

var nodeMap = {};
GRAPH_DATA.nodes.forEach(function(n) { nodeMap[n.id] = n; });

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

var visNodes = GRAPH_DATA.nodes.map(function(n) {
  var color = PARA_COLORS[n.para] || "#9B9B9B";
  return {
    id: n.id,
    label: n.label,
    color: {
      background: color,
      border: color,
      highlight: { background: color, border: "#FAFAFA" },
      hover:     { background: color, border: "#FAFAFA" }
    },
    font:  { color: "#FAFAFA", size: 13, face: "Segoe UI, sans-serif" },
    shape: "dot",
    size:  18,
    shadow: { enabled: true, color: color, size: 8, x: 0, y: 0 },
    title: "<b>" + escapeHtml(n.label) + "</b><br>"
         + "<span style='color:#888'>" + escapeHtml(n.para) + "</span><br><br>"
         + escapeHtml(n.summary),
    borderWidth: 0,
    borderWidthSelected: 2
  };
});

var visEdges = GRAPH_DATA.edges.map(function(e, i) {
  var opacity = Math.max(0.25, Math.min(1.0, e.weight));
  return {
    id: "e" + i,
    from: e.source,
    to:   e.target,
    width: Math.max(1, e.weight * 4),
    color: { color: "rgba(255,255,255," + opacity.toFixed(2) + ")", opacity: 1 },
    smooth: { type: "continuous", roundness: 0.2 },
    arrows: { to: { enabled: false } },
    title: "Similarity: " + e.weight.toFixed(4)
  };
});

var options = {
  physics: {
    enabled: true,
    solver: "forceAtlas2Based",
    forceAtlas2Based: {
      gravitationalConstant: -40,
      centralGravity: 0.008,
      springLength: 160,
      springConstant: 0.04,
      damping: 0.4,
      avoidOverlap: 0.6
    },
    stabilization: { iterations: 200, fit: true },
    maxVelocity: 30,
    minVelocity: 0.5
  },
  interaction: {
    hover: true,
    tooltipDelay: 200,
    dragNodes: true,
    dragView: true,
    zoomView: true,
    navigationButtons: false,
    keyboard: { enabled: true }
  }
};

var container = document.getElementById("graph");
var data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
var network = new vis.Network(container, data, options);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading knowledge graph...")
def load_graph() -> dict:
    """Load and cache data/graph.json."""
    if not GRAPH_PATH.exists():
        return {}
    try:
        return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@st.cache_resource(show_spinner="Building wiki index (first run may download model)...")
def get_wiki_index() -> dict[str, Any]:
    """Build and cache the wiki embedding index (heavy singleton)."""
    from link import build_wiki_index
    return build_wiki_index()


@st.cache_data(show_spinner="Rendering graph...")
def build_graph_html(graph: dict) -> str:
    """Inject graph JSON into the vis-network HTML template."""
    return _GRAPH_HTML_TEMPLATE.replace("__GRAPH_JSON__", json.dumps(graph))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_cloud_env() -> bool:
    """Return True when running on Streamlit Community Cloud."""
    import os
    return (
        os.environ.get("STREAMLIT_SHARING_MODE") == "streamlit-sharing"
        or os.environ.get("IS_CLOUD", "").lower() in {"1", "true", "yes"}
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _clear_all_caches() -> None:
    """Clear every cached resource so the app picks up new data."""
    load_graph.clear()
    build_graph_html.clear()
    get_wiki_index.clear()


def render_capture_section() -> None:
    """Capture new notes or links from the sidebar and optionally run the pipeline."""
    st.markdown("### Capture")

    # Cloud-safe notice: Streamlit Community Cloud has no persistent disk.
    # Captures written here survive the session but are lost on next deploy/restart.
    if not (PROJECT_ROOT / "raw").is_mount() and _is_cloud_env():
        st.info(
            "⚠️ **Streamlit Cloud**: captures written here are not persisted across "
            "restarts. Run the pipeline locally and push `wiki/` + `data/graph.json` "
            "to GitHub to update the deployed app.",
            icon="☁️",
        )

    capture_mode = st.radio(
        "Capture type",
        ["Note", "Link"],
        horizontal=True,
        key="capture_mode",
        label_visibility="collapsed",
    )

    if capture_mode == "Note":
        note_text = st.text_area(
            "New note",
            placeholder="Type a thought, idea, or snippet...",
            height=100,
            key="capture_note_text",
            label_visibility="collapsed",
        )
        link_url = None
    else:
        note_text = None
        link_url = st.text_input(
            "URL",
            placeholder="https://...",
            key="capture_link_url",
            label_visibility="collapsed",
        )

    run_pipeline = st.checkbox("Run pipeline after capture", value=True, key="capture_run_pipeline")

    if st.button("Capture", use_container_width=True, type="primary", key="capture_btn"):
        try:
            if capture_mode == "Note":
                text = (note_text or "").strip()
                if not text:
                    st.warning("Please enter some note text.")
                    return
                from capture import capture_note
                record = capture_note(text, source="streamlit")
            else:
                url = (link_url or "").strip()
                if not url:
                    st.warning("Please enter a URL.")
                    return
                from capture import capture_link
                record = capture_link(url, source="streamlit")

            st.success(f"Captured -> `{record.file_path.name}`")

            if run_pipeline:
                with st.spinner("Running pipeline (classify + link + graph)..."):
                    from pipeline import _run_classify, _run_link
                    from build_graph import build_graph as rebuild_graph

                    _run_classify()
                    _run_link()
                    rebuild_graph()

                _clear_all_caches()
                st.success("Pipeline complete! Graph updated.")
                st.rerun()

        except Exception as exc:
            st.error(f"Capture failed: {exc}")


def _save_api_key_to_env(api_key: str, model: str) -> None:
    """Persist API key and model to .env and .streamlit/secrets.toml."""
    env_file = PROJECT_ROOT / ".env"
    lines = []
    has_groq = False
    has_model = False
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GROQ_API_KEY="):
                lines.append(f'GROQ_API_KEY="{api_key}"')
                has_groq = True
            elif line.strip().startswith("LLM_MODEL="):
                lines.append(f'LLM_MODEL="{model}"')
                has_model = True
            else:
                lines.append(line)
    if not has_groq:
        lines.append(f'GROQ_API_KEY="{api_key}"')
    if not has_model:
        lines.append(f'LLM_MODEL="{model}"')

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Also update .streamlit/secrets.toml if present
    secrets_file = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if secrets_file.exists():
        s_lines = []
        for line in secrets_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GROQ_API_KEY"):
                s_lines.append(f'GROQ_API_KEY = "{api_key}"')
            else:
                s_lines.append(line)
        secrets_file.write_text("\n".join(s_lines) + "\n", encoding="utf-8")


def render_api_settings_section() -> None:
    """Render the API Key and model settings in the sidebar."""
    with st.expander("🔑 Groq API & Model Settings", expanded=False):
        from ask import resolve_groq_api_key, validate_groq_api_key

        current_key = resolve_groq_api_key() or ""
        is_configured = bool(current_key)

        if is_configured:
            masked = current_key[:6] + "..." + current_key[-4:] if len(current_key) > 12 else "******"
            st.caption(f"Active Key: `{masked}`")
        else:
            st.caption("Status: 🔴 No valid API key configured")

        input_key = st.text_input(
            "Groq API Key",
            value=st.session_state.get("groq_api_key", current_key),
            type="password",
            placeholder="gsk_...",
            key="groq_key_input_box",
            help="Get a free key from console.groq.com/keys",
        )

        model_options = [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "mixtral-8x7b-32768",
        ]
        curr_model = st.session_state.get("groq_model") or os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")
        if curr_model not in model_options:
            curr_model = "llama-3.1-8b-instant"

        chosen_model = st.selectbox(
            "Model",
            options=model_options,
            index=model_options.index(curr_model),
            key="groq_model_box",
        )

        col_save, col_clear = st.columns([1, 1])
        with col_save:
            if st.button("Save & Test", use_container_width=True, type="primary", key="save_groq_key_btn"):
                key_clean = input_key.strip()
                if not key_clean:
                    st.warning("Please enter an API key.")
                else:
                    with st.spinner("Verifying key with Groq..."):
                        valid, message = validate_groq_api_key(key_clean)
                    if valid:
                        st.session_state["groq_api_key"] = key_clean
                        st.session_state["groq_model"] = chosen_model
                        os.environ["GROQ_API_KEY"] = key_clean
                        os.environ["LLM_MODEL"] = chosen_model
                        _save_api_key_to_env(key_clean, chosen_model)
                        st.success("✅ Connected & saved!")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")

        with col_clear:
            if st.button("Clear", use_container_width=True, key="clear_groq_key_btn"):
                st.session_state["groq_api_key"] = ""
                os.environ.pop("GROQ_API_KEY", None)
                _save_api_key_to_env("", chosen_model)
                st.info("API Key cleared.")
                st.rerun()

        st.markdown(
            "👉 [Get a free Groq API key](https://console.groq.com/keys)",
            unsafe_allow_html=True,
        )


def render_sidebar(graph: dict) -> None:
    """Populate the Streamlit sidebar with stats, capture form, and PARA breakdown."""
    with st.sidebar:
        st.markdown("## SecondSelf")
        st.caption("Personal AI Second Brain")
        st.markdown("---")

        # --- Statistics ---
        if graph:
            meta = graph.get("meta", {})
            nodes = graph.get("nodes", [])

            st.markdown("### Statistics")
            col1, col2 = st.columns(2)
            col1.metric("Nodes", meta.get("node_count", len(nodes)))
            col2.metric("Edges", meta.get("edge_count", len(graph.get("edges", []))))

            gen_at = meta.get("generated_at", "")
            if gen_at:
                st.caption(f"Generated: {gen_at[:10]}")

            st.markdown("---")
            st.markdown("### PARA Categories")

            para_counts: dict[str, int] = {}
            for node in nodes:
                para = node.get("para", "Resources")
                para_counts[para] = para_counts.get(para, 0) + 1

            for para, color in PARA_COLORS.items():
                count = para_counts.get(para, 0)
                st.markdown(
                    f"<span style='display:inline-block;width:12px;height:12px;"
                    f"border-radius:50%;background:{color};margin-right:8px;"
                    f"vertical-align:middle;'></span>"
                    f"<span style='vertical-align:middle;'>{para}</span>"
                    f"<span style='float:right;color:#888;'>{count}</span>",
                    unsafe_allow_html=True,
                )

            st.markdown("---")
        else:
            st.warning("No graph found. Capture notes below and run the pipeline to build one.")
            st.markdown("---")

        # --- API Key settings section ---
        render_api_settings_section()

        st.markdown("---")

        # --- Capture section (always visible) ---
        render_capture_section()

        st.markdown("---")

        # --- Refresh ---
        if st.button("Refresh graph", use_container_width=True):
            _clear_all_caches()
            st.rerun()


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

def render_ask_section() -> None:
    """Render the ask bar and answer panel."""
    st.markdown("# 🧠 SecondSelf")
    st.caption("Your Personal AI Second Brain — ask anything about your knowledge.")

    # Input row (no st.form — avoids batched-input quirks)
    input_col, btn_col = st.columns([5, 1])
    with input_col:
        question_input = st.text_input(
            "Ask a question",
            placeholder="e.g. What projects am I working on?",
            label_visibility="collapsed",
            key="ask_input",
        )
    with btn_col:
        # Pad to vertically align with the text input
        st.markdown("<br>", unsafe_allow_html=True)
        ask_clicked = st.button("Ask", use_container_width=True, type="primary")

    # When the user clicks Ask (or presses Enter, which also reruns the page),
    # fire the RAG query and stash the result in session state so it persists.
    if ask_clicked:
        question = (question_input or "").strip()
        if not question:
            st.info("Please type a question and press **Ask**.")
        else:
            with st.spinner("Searching your notes and synthesizing an answer..."):
                try:
                    index = get_wiki_index()
                    from ask import ask as ask_question
                    active_key = st.session_state.get("groq_api_key")
                    active_model = st.session_state.get("groq_model")
                    st.session_state["ask_result"] = ask_question(
                        question,
                        top_k=RAG_TOP_K,
                        index=index,
                        api_key=active_key,
                        model=active_model,
                    )
                except Exception as exc:
                    st.error(f"Query error: {exc}")

    # Render any previous or just-computed answer
    result = st.session_state.get("ask_result")
    if result is not None:
        st.markdown("---")
        st.markdown("### Answer")
        st.markdown(result.answer)

        if "Invalid or unconfigured Groq API Key" in result.answer:
            st.info(
                "💡 **Groq API Tip**: Enter your Groq API key in the sidebar under **🔑 Groq API & Model Settings** "
                "or update your `.env` file to enable conversational AI synthesis. ([Get a free key here](https://console.groq.com/keys))"
            )

        if result.sources:
            with st.expander(f"Sources ({len(result.sources)} notes)", expanded=False):
                for i, src in enumerate(result.sources, 1):
                    badge = PARA_COLORS.get(src.para, "#888")
                    st.markdown(
                        f"<span style='display:inline-block;width:10px;height:10px;"
                        f"border-radius:50%;background:{badge};margin-right:6px;"
                        f"vertical-align:middle;'></span>"
                        f"<b>{i}. {src.slug}</b> "
                        f"<span style='color:#888;'>[{src.para}] "
                        f"— score: {src.score:.3f}</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"`{src.path}`")
                    if src.summary:
                        st.caption(src.summary)


def render_graph(graph: dict) -> None:
    """Render the interactive knowledge graph."""
    st.markdown("---")
    st.markdown("### Knowledge Graph")

    if not graph:
        st.info(
            "No graph data available. Run `python build_graph.py` to generate it."
        )
        return

    html = build_graph_html(graph)
    components.html(html, height=GRAPH_HEIGHT, scrolling=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    graph = load_graph()
    render_sidebar(graph)
    render_ask_section()
    render_graph(graph)


if __name__ == "__main__":
    main()
