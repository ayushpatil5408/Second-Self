"""Vercel Serverless Entrypoint for SecondSelf.

Provides standard WSGI and BaseHTTPRequestHandler entrypoints to satisfy
Vercel's Python runtime while serving the stunning WebGL animated login UI.
"""

from http.server import BaseHTTPRequestHandler
import mimetypes
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Ensure MIME types are registered
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")


def _get_target_file(raw_path: str) -> Path:
    clean_path = raw_path.split("?")[0].lstrip("/")
    if not clean_path or clean_path in ("login", "index"):
        target = BASE_DIR / "login.html"
        if not target.exists():
            target = BASE_DIR / "index.html"
        return target

    candidate = BASE_DIR / clean_path
    if candidate.is_file():
        return candidate

    fallback = BASE_DIR / "login.html"
    if fallback.exists():
        return fallback
    return BASE_DIR / "index.html"


class handler(BaseHTTPRequestHandler):
    """BaseHTTPRequestHandler for Vercel serverless runtime."""

    def do_GET(self):
        target_file = _get_target_file(self.path)
        if target_file.is_file():
            content = target_file.read_bytes()
            content_type, _ = mimetypes.guess_type(str(target_file))
            content_type = content_type or "application/octet-stream"
            if "text" in content_type or "javascript" in content_type:
                content_type += "; charset=utf-8"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found")


def app(environ, start_response):
    """WSGI standard entrypoint for Vercel Python runtime."""
    raw_path = environ.get("PATH_INFO", "/")
    target_file = _get_target_file(raw_path)

    if target_file.is_file():
        content = target_file.read_bytes()
        content_type, _ = mimetypes.guess_type(str(target_file))
        content_type = content_type or "application/octet-stream"
        if "text" in content_type or "javascript" in content_type:
            content_type += "; charset=utf-8"

        start_response("200 OK", [
            ("Content-Type", content_type),
            ("Content-Length", str(len(content))),
        ])
        return [content]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"404 Not Found"]
