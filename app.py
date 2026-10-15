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
def load_graph(user_id: str | None = None) -> dict:
    """Load and cache graph.json for the current user."""
    from config import get_user_workspace
    graph_path = get_user_workspace(user_id)["graph_path"]
    if not graph_path.exists():
        return {}
    try:
        return json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@st.cache_resource(show_spinner="Building wiki index (first run may download model)...")
def get_wiki_index(user_id: str | None = None) -> dict[str, Any]:
    """Build and cache the wiki embedding index for the current user."""
    from config import get_user_workspace
    from link import build_wiki_index
    ws = get_user_workspace(user_id)
    return build_wiki_index(wiki_dir=ws["wiki_dir"], embeddings_dir=ws["embeddings_dir"])


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


def render_capture_section(user: dict | None = None) -> None:
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

    if "uploader_rev" not in st.session_state:
        st.session_state["uploader_rev"] = 0
    rev = st.session_state["uploader_rev"]
    user_id = user.get("id") if user else None

    # Three prominent, clearly visible tabs for capture
    tab_note, tab_link, tab_media = st.tabs(["📝 Note", "🔗 Link", "📁 Attach Media"])

    note_text = None
    note_file = None
    link_url = None
    media_file = None
    media_caption = ""
    action_type = None

    with tab_note:
        note_text = st.text_area(
            "New note",
            placeholder="Type a thought, idea, or snippet...",
            height=90,
            key=f"capture_note_text_{rev}",
            label_visibility="collapsed",
        )
        note_file = st.file_uploader(
            "📎 Optional: attach an image or file",
            key=f"note_attach_file_{rev}",
            help="Optionally attach an image, PDF, or document alongside this note",
        )
        if note_file is not None:
            st.caption(f"📎 Attached: `{note_file.name}` ({note_file.size / 1024:.1f} KB)")
        if st.button("Capture Note", use_container_width=True, type="primary", key=f"btn_cap_note_{rev}"):
            action_type = "note"

    with tab_link:
        link_url = st.text_input(
            "URL",
            placeholder="https://...",
            key=f"capture_link_url_{rev}",
            label_visibility="collapsed",
        )
        if st.button("Capture Link", use_container_width=True, type="primary", key=f"btn_cap_link_{rev}"):
            action_type = "link"

    with tab_media:
        st.caption("Upload images, audio recordings, PDFs, or documents directly into your Second Brain:")
        media_file = st.file_uploader(
            "Upload media or file",
            type=None,
            key=f"capture_media_file_{rev}",
            label_visibility="collapsed",
            help="Images (PNG, JPG, WEBP, GIF), Audio (MP3, WAV, M4A), PDF, Word, Code, Data",
        )
        media_caption = st.text_input(
            "Caption / Note (optional)",
            placeholder="e.g. Brainstorm sketch, Sprint voice memo, Invoice...",
            key=f"capture_media_caption_{rev}",
        )

        if media_file is not None:
            from media_extractor import get_media_category
            cat = get_media_category(media_file.name)
            file_kb = media_file.size / 1024
            st.caption(f"📁 **{media_file.name}** ({file_kb:.1f} KB) · `{cat}`")

            if cat == "image":
                st.image(media_file, caption=media_file.name, use_container_width=True)
            elif cat == "audio":
                st.audio(media_file)
            elif cat == "video":
                st.video(media_file)

        if st.button("Upload & Capture File", use_container_width=True, type="primary", key=f"btn_cap_media_{rev}"):
            action_type = "media"

    run_pipeline = st.checkbox("Run AI pipeline after capture", value=True, key="capture_run_pipeline")

    if action_type:
        try:
            records = []
            if action_type == "note":
                text = (note_text or "").strip()
                if not text and note_file is None:
                    st.warning("Please enter some note text or attach a file.")
                    return
                if text:
                    from capture import capture_note
                    rec = capture_note(text, source="streamlit", user_id=user_id)
                    records.append(rec)
                if note_file is not None:
                    from capture import capture_media
                    rec_media = capture_media(
                        note_file.getvalue(),
                        original_filename=note_file.name,
                        source="streamlit",
                        caption=f"Attached to note: {text[:60]}" if text else "",
                        user_id=user_id,
                    )
                    records.append(rec_media)

            elif action_type == "link":
                url = (link_url or "").strip()
                if not url:
                    st.warning("Please enter a URL.")
                    return
                from capture import capture_link
                rec = capture_link(url, source="streamlit", user_id=user_id)
                records.append(rec)

            elif action_type == "media":
                if media_file is None:
                    st.warning("Please select a file to upload.")
                    return
                from capture import capture_media
                rec = capture_media(
                    media_file.getvalue(),
                    original_filename=media_file.name,
                    source="streamlit",
                    caption=media_caption.strip(),
                    user_id=user_id,
                )
                records.append(rec)

            # Advance uploader revision to reset fields
            st.session_state["uploader_rev"] = rev + 1
            if records:
                st.session_state["last_captured_name"] = records[0].file_path.name

            if run_pipeline:
                with st.spinner("Running pipeline (media analysis + classify + link + graph)..."):
                    if user_id:
                        from pipeline import run_pipeline_for_user
                        run_pipeline_for_user(user_id)
                    else:
                        from pipeline import _run_classify, _run_link
                        from build_graph import build_graph as rebuild_graph
                        _run_classify()
                        _run_link()
                        rebuild_graph()

                _clear_all_caches()
                st.toast("Captured & analyzed successfully!", icon="✅")
                st.rerun()
            else:
                st.toast("Captured successfully!", icon="✅")
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


def render_sidebar(graph: dict, user: dict | None = None) -> None:
    """Populate the Streamlit sidebar with stats, capture form, and PARA breakdown."""
    with st.sidebar:
        st.markdown("## SecondSelf")
        st.caption("Personal AI Second Brain")
        st.markdown("---")

        # --- User profile & Log Out ---
        if user:
            col_pic, col_name = st.columns([1, 3])
            with col_pic:
                pic = user.get("picture")
                if pic:
                    st.markdown(
                        f"<img src='{pic}' style='width:38px;height:38px;border-radius:50%;border:1px solid #4A90D9;'>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown("👤")
            with col_name:
                st.markdown(f"**{user.get('name', 'User')}**")
                prov = "🔴 Google" if user.get("provider") == "google" else "✉️ Email"
                st.caption(f"{user.get('email', '')} · `{prov}`")

            from auth_ui import logout_user
            if st.button("Log Out", use_container_width=True, key="sidebar_logout_btn"):
                logout_user()
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
        render_capture_section(user=user)

        st.markdown("---")

        # --- Refresh ---
        if st.button("Refresh graph", use_container_width=True):
            _clear_all_caches()
            st.rerun()


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

def render_ask_section(user: dict | None = None) -> None:
    """Render the ask bar and answer panel for the current user."""
    st.markdown("# 🧠 SecondSelf")
    st.caption("Your Personal AI Second Brain — ask anything about your knowledge.")

    user_id = user.get("id") if user else None

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
                    index = get_wiki_index(user_id)
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
                    err_str = str(exc)
                    if "GROQ_API_KEY" in err_str or "api_key" in err_str.lower() or "401" in err_str:
                        st.warning("⚠️ **Groq API Key Not Configured**")
                        st.info("To ask questions and get AI answers, enter your Groq API key below (or add it in your Streamlit Cloud Secrets):")
                        with st.form("inline_groq_config_form"):
                            entered_key = st.text_input("Groq API Key", type="password", placeholder="gsk_...", label_visibility="collapsed")
                            if st.form_submit_button("Save Key & Run Query", type="primary"):
                                if entered_key.strip():
                                    st.session_state["groq_api_key"] = entered_key.strip()
                                    os.environ["GROQ_API_KEY"] = entered_key.strip()
                                    _save_api_key_to_env(entered_key.strip(), LLM_MODEL)
                                    st.success("API key saved! Rerunning query...")
                                    st.rerun()
                                else:
                                    st.error("Please enter a valid Groq API key.")
                    else:
                        st.error(f"Query error: {exc}")


    # Render any previous or just-computed answer
    result = st.session_state.get("ask_result")
    if result is not None:
        st.markdown("---")

        # --- Detect and showcase matched media files prominently ---
        from config import get_user_workspace
        from media_extractor import resolve_media_file

        user_raw = get_user_workspace(user_id)["raw_dir"]
        matched_media: list[tuple[Any, str, Path, str]] = []
        if result.sources:
            for src in result.sources:
                cat, f_path, d_name = resolve_media_file(src, raw_dir=user_raw)
                if f_path and f_path.exists() and cat in {"image", "audio", "video", "document"}:
                    matched_media.append((src, cat, f_path, d_name))

        if matched_media:
            st.markdown("### 📸 Matched Media & Files")
            for idx, (src, cat, f_path, d_name) in enumerate(matched_media):
                if cat == "image":
                    col_img, col_info = st.columns([3, 2])
                    with col_img:
                        st.image(str(f_path), caption=f"{d_name}", use_container_width=True)
                    with col_info:
                        st.markdown(f"#### 🖼️ {d_name}")
                        badge = PARA_COLORS.get(src.para, "#888")
                        st.markdown(
                            f"<span style='display:inline-block;width:10px;height:10px;"
                            f"border-radius:50%;background:{badge};margin-right:6px;"
                            f"vertical-align:middle;'></span>"
                            f"<b>Category:</b> {src.para}",
                            unsafe_allow_html=True,
                        )
                        if src.summary:
                            st.caption(f"**Summary:** {src.summary}")
                        try:
                            file_size_kb = f_path.stat().st_size / 1024
                            st.caption(f"**File Size:** {file_size_kb:.1f} KB")
                        except Exception:
                            pass

                        with open(f_path, "rb") as f_data:
                            st.download_button(
                                label=f"⬇️ Download {d_name}",
                                data=f_data.read(),
                                file_name=d_name,
                                key=f"showcase_dl_{idx}_{src.note_id}",
                                use_container_width=True,
                            )
                elif cat == "audio":
                    st.markdown(f"#### 🎵 Audio: {d_name} `[{src.para}]`")
                    st.audio(str(f_path))
                    if src.summary:
                        st.caption(src.summary)
                    with open(f_path, "rb") as f_data:
                        st.download_button(
                            label=f"⬇️ Download Audio: {d_name}",
                            data=f_data.read(),
                            file_name=d_name,
                            key=f"showcase_dl_{idx}_{src.note_id}",
                        )
                elif cat == "video":
                    st.markdown(f"#### 🎬 Video: {d_name} `[{src.para}]`")
                    st.video(str(f_path))
                elif cat == "document":
                    st.markdown(f"#### 📄 Document: {d_name} `[{src.para}]`")
                    if src.summary:
                        st.caption(src.summary)
                    with open(f_path, "rb") as f_data:
                        st.download_button(
                            label=f"⬇️ Download Document: {d_name}",
                            data=f_data.read(),
                            file_name=d_name,
                            key=f"showcase_dl_{idx}_{src.note_id}",
                        )
            st.markdown("---")

        st.markdown("### Answer")
        st.markdown(result.answer)

        if "Invalid or unconfigured Groq API Key" in result.answer:
            st.info(
                "💡 **Groq API Tip**: Enter your Groq API key in the sidebar under **🔑 Groq API & Model Settings** "
                "or update your `.env` file to enable conversational AI synthesis. ([Get a free key here](https://console.groq.com/keys))"
            )

        if result.sources:
            with st.expander(f"Sources ({len(result.sources)} notes & files)", expanded=bool(matched_media)):
                for i, src in enumerate(result.sources, 1):
                    badge = PARA_COLORS.get(src.para, "#888")
                    cat, f_path, d_name = resolve_media_file(src)
                    media_tag = ""
                    if cat and cat in {"image", "audio", "video", "document", "archive"}:
                        type_icons = {
                            "image": "🖼️ Image",
                            "audio": "🎵 Audio",
                            "video": "🎬 Video",
                            "document": "📄 Document",
                            "archive": "📦 Archive",
                        }
                        icon_label = type_icons.get(cat, "📁 File")
                        media_tag = f" · <span style='background:#2a2d36;padding:2px 6px;border-radius:4px;font-size:12px;'>{icon_label}: {d_name}</span>"

                    st.markdown(
                        f"<div style='margin-top:10px;margin-bottom:4px;'>"
                        f"<span style='display:inline-block;width:10px;height:10px;"
                        f"border-radius:50%;background:{badge};margin-right:6px;"
                        f"vertical-align:middle;'></span>"
                        f"<b>{i}. {src.slug}</b> "
                        f"<span style='color:#888;'>[{src.para}] "
                        f"— score: {src.score:.3f}</span>"
                        f"{media_tag}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"`{src.path}`")
                    if src.summary:
                        st.caption(src.summary)

                    # Show media preview or download if file is present
                    if f_path and f_path.exists():
                        if cat == "image":
                            st.image(str(f_path), caption=d_name, width=320)
                        elif cat == "audio":
                            st.audio(str(f_path))
                        elif cat in {"document", "video", "archive", "file", "text"}:
                            with open(f_path, "rb") as f_data:
                                st.download_button(
                                    label=f"⬇️ Download {d_name}",
                                    data=f_data.read(),
                                    file_name=d_name,
                                    key=f"dl_{i}_{src.note_id}",
                                )


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
    from auth_ui import get_current_user, render_login_page

    user = get_current_user()
    if not user:
        render_login_page()
        return

    user_id = user.get("id")
    graph = load_graph(user_id)
    render_sidebar(graph, user=user)
    render_ask_section(user=user)
    render_graph(graph)


if __name__ == "__main__":
    main()
