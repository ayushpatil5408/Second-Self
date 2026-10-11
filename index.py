"""Vercel Serverless Full-Stack Backend for SecondSelf.

Provides:
- Web UI serving (index.html with WebGL particle drift & Vis.js Knowledge Graph)
- Google OAuth 2.0 token exchange (/api/auth/google/callback)
- Knowledge Graph API (/api/graph)
- AI Oracle RAG endpoint powered by Groq LLM (/api/ask)
- Note Capture API (/api/capture)
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GRAPH_FILE = DATA_DIR / "graph.json"
WIKI_DIR = BASE_DIR / "wiki"

# Ensure MIME types are registered
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

# Load environment variables from .env if present
def _load_env_file() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

_load_env_file()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b").strip()



def _get_graph_data() -> dict:
    if GRAPH_FILE.exists():
        try:
            return json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"nodes": [], "edges": [], "meta": {"node_count": 0, "edge_count": 0}}


def _exchange_google_code(code: str, redirect_uri: str) -> dict:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return {
            "success": False,
            "error": "Google OAuth is not configured on Vercel. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Vercel Environment Variables."
        }
    token_url = "https://oauth2.googleapis.com/token"
    post_data = urllib.parse.urlencode({
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=post_data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "SecondSelf/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))

        access_token = token_json.get("access_token")
        if not access_token:
            return {"success": False, "error": "No access token received from Google"}

        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        user_req = urllib.request.Request(userinfo_url, headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "SecondSelf/1.0",
        })
        with urllib.request.urlopen(user_req, timeout=15) as u_resp:
            profile = json.loads(u_resp.read().decode("utf-8"))

        return {
            "success": True,
            "user": {
                "email": profile.get("email"),
                "name": profile.get("name") or profile.get("email", "").split("@")[0],
                "picture": profile.get("picture") or "https://api.dicebear.com/7.x/initials/svg?seed=" + profile.get("name", "User"),
            }
        }
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
        except Exception:
            err_body = str(exc)
        return {"success": False, "error": f"Google Token Exchange Error ({exc.code}): {err_body}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _answer_with_groq(query: str) -> dict:
    api_key = GROQ_API_KEY or os.environ.get("GROQ_API_KEY", "")
    graph_data = _get_graph_data()
    nodes = graph_data.get("nodes", [])

    # Rank nodes by keyword overlap with query
    words = set(query.lower().split())
    scored = []
    for node in nodes:
        score = 0
        text = f"{node.get('label', '')} {node.get('summary', '')} {' '.join(node.get('tags', []))} {node.get('content_preview', '')}".lower()
        for w in words:
            if len(w) > 2 and w in text:
                score += 1
        scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_nodes = [n for s, n in scored[:5] if s > 0] or [n for s, n in scored[:3]]

    notes_context = []
    for n in top_nodes:
        notes_context.append(
            f"Title: {n.get('label')}\nCategory: {n.get('para')}\nSummary: {n.get('summary')}\nContent Preview: {n.get('content_preview')}\n"
        )
    context_str = "\n---\n".join(notes_context)

    if not api_key:
        return {
            "answer": "Groq API key is not configured in environment. Displaying matched notes below.",
            "sources": [{"title": n.get("label"), "para": n.get("para"), "summary": n.get("summary")} for n in top_nodes]
        }

    system_prompt = (
        "You are SecondSelf, an intelligent second brain assistant. Answer the user's question "
        "concisely and accurately using ONLY the personal notes provided below. "
        "Cite note titles in bold when referencing them. If the notes do not have enough info, say so clearly."
    )
    user_prompt = f"--- NOTES ---\n{context_str}\n--- END NOTES ---\n\nQuestion: {query}"

    req_body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 600
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SecondSelf/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            return {
                "answer": answer,
                "sources": [{"title": n.get("label"), "para": n.get("para"), "summary": n.get("summary")} for n in top_nodes]
            }
    except Exception as exc:
        return {
            "answer": f"Unable to generate response via LLM ({exc}). Here are relevant notes from your knowledge graph:",
            "sources": [{"title": n.get("label"), "para": n.get("para"), "summary": n.get("summary")} for n in top_nodes]
        }


def _capture_note(payload: dict) -> dict:
    title = payload.get("title", "Quick Capture").strip()
    content = payload.get("content", "").strip()
    para = payload.get("para", "Resources").strip()
    tags = payload.get("tags", [])

    if not content:
        return {"success": False, "error": "Content cannot be empty"}

    import hashlib
    node_id = hashlib.md5(f"{title}-{content}".encode("utf-8")).hexdigest()[:8]

    new_node = {
        "id": node_id,
        "label": title,
        "para": para,
        "tags": tags,
        "summary": content[:120] + ("..." if len(content) > 120 else ""),
        "content_preview": content[:240],
        "path": f"wiki/{para}/{node_id}.md"
    }

    graph = _get_graph_data()
    graph["nodes"].append(new_node)
    graph["meta"]["node_count"] = len(graph["nodes"])

    try:
        GRAPH_FILE.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {"success": True, "node": new_node}


def app(environ, start_response):
    """WSGI standard entrypoint for Vercel Python runtime."""
    raw_path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query_string = environ.get("QUERY_STRING", "")
    params = urllib.parse.parse_qs(query_string)

    # 1. API Routes
    if raw_path == "/api/graph":
        data = json.dumps(_get_graph_data()).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
        ])
        return [data]

    if raw_path == "/api/auth/google/url":
        redirect_uri = params.get("redirect_uri", [""])[0] or "https://second-self-1mbv-sigma.vercel.app/"
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account consent",
        })
        data = json.dumps({"auth_url": auth_url, "client_id": GOOGLE_CLIENT_ID}).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
        ])
        return [data]

    if raw_path == "/api/auth/google/callback":
        code = params.get("code", [""])[0]
        redirect_uri = params.get("redirect_uri", [""])[0]
        result = _exchange_google_code(code, redirect_uri)
        data = json.dumps(result).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
        ])
        return [data]

    if raw_path == "/api/ask" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", 0) or 0)
            body = environ["wsgi.input"].read(length)
            payload = json.loads(body.decode("utf-8")) if body else {}
            query = payload.get("query", "")
            result = _answer_with_groq(query)
        except Exception as e:
            result = {"answer": f"Error: {e}", "sources": []}

        data = json.dumps(result).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
        ])
        return [data]

    if raw_path == "/api/capture" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", 0) or 0)
            body = environ["wsgi.input"].read(length)
            payload = json.loads(body.decode("utf-8")) if body else {}
            result = _capture_note(payload)
        except Exception as e:
            result = {"success": False, "error": str(e)}

        data = json.dumps(result).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
        ])
        return [data]

    # 2. Static Assets Serving
    clean_path = raw_path.lstrip("/")
    if not clean_path or clean_path in ("login", "index"):
        target_file = BASE_DIR / "index.html"
    else:
        target_file = BASE_DIR / clean_path

    if target_file.is_file():
        content = target_file.read_bytes()
        content_type, _ = mimetypes.guess_type(str(target_file))
        content_type = content_type or "application/octet-stream"
        if "text" in content_type or "javascript" in content_type or "json" in content_type:
            content_type += "; charset=utf-8"

        start_response("200 OK", [
            ("Content-Type", content_type),
            ("Content-Length", str(len(content))),
        ])
        return [content]

    # Fallback to index.html
    fallback = BASE_DIR / "index.html"
    if fallback.is_file():
        content = fallback.read_bytes()
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(content))),
        ])
        return [content]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"404 Not Found"]


class handler(BaseHTTPRequestHandler):
    """Fallback BaseHTTPRequestHandler adapter."""
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        parsed = urllib.parse.urlparse(self.path)
        env = {
            "PATH_INFO": parsed.path,
            "REQUEST_METHOD": method,
            "QUERY_STRING": parsed.query,
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            "wsgi.input": self.rfile,
        }
        res_headers = []
        status_code = [200]

        def start_response(status, headers):
            status_code[0] = int(status.split()[0])
            res_headers.extend(headers)

        body = app(env, start_response)
        self.send_response(status_code[0])
        for k, v in res_headers:
            self.send_header(k, v)
        self.end_headers()
        for chunk in body:
            self.wfile.write(chunk)
