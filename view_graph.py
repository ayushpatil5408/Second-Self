"""Phase 3.2 — Interactive graph visualization.

Reads ``data/graph.json`` and the HTML template ``graph_component.html``,
injects the graph data inline, and either writes a standalone HTML file
or serves it on a local HTTP server.

Usage:
    python view_graph.py                  # build HTML + start local server
    python view_graph.py --output out.html  # write standalone file only
    python view_graph.py --port 8501      # custom server port
    python view_graph.py --no-serve       # build HTML, don't start server
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from config import DATA_DIR, GRAPH_PATH, PROJECT_ROOT

TEMPLATE_PATH = PROJECT_ROOT / "graph_component.html"
DEFAULT_OUTPUT = DATA_DIR / "graph_view.html"
PLACEHOLDER = "__GRAPH_JSON__"
DEFAULT_PORT = 8765


# ---------------------------------------------------------------------------
# Graph HTML builder
# ---------------------------------------------------------------------------

def build_graph_html(
    graph_path: Path = GRAPH_PATH,
    template_path: Path = TEMPLATE_PATH,
) -> str:
    """Read graph JSON and inject it into the HTML template.

    Returns:
        Complete standalone HTML string with embedded graph data.
    """
    if not graph_path.exists():
        raise FileNotFoundError(
            f"Graph file not found: {graph_path}\n"
            "Run `python build_graph.py` first."
        )
    if not template_path.exists():
        raise FileNotFoundError(
            f"HTML template not found: {template_path}"
        )

    graph_json = graph_path.read_text(encoding="utf-8").strip()
    # Validate JSON
    json.loads(graph_json)

    template = template_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(
            f"Template is missing the '{PLACEHOLDER}' injection point."
        )

    return template.replace(PLACEHOLDER, graph_json)


def write_graph_html(
    output_path: Path = DEFAULT_OUTPUT,
    graph_path: Path = GRAPH_PATH,
) -> Path:
    """Build and write the standalone graph HTML file."""
    html = build_graph_html(graph_path)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Local HTTP server
# ---------------------------------------------------------------------------

class _QuietHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves a single HTML string at /."""

    html_content: str = ""

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html", "/graph"):
            payload = self.html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        # Suppress default stderr logging
        pass


def serve_graph_html(
    html_content: str,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> None:
    """Start a local HTTP server serving the graph HTML at /."""
    _QuietHandler.html_content = html_content

    server = HTTPServer(("127.0.0.1", port), _QuietHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"Serving graph at {url}")
    print("  Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize the SecondSelf knowledge graph in a browser."
    )
    parser.add_argument(
        "--output", "-o",
        help=f"Output path for standalone HTML (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--port", "-p", type=int, default=DEFAULT_PORT,
        help=f"Local server port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-serve", action="store_true",
        help="Write HTML file only, do not start server.",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not auto-open the browser.",
    )
    parser.add_argument(
        "--graph",
        help=f"Path to graph JSON (default: {GRAPH_PATH}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    graph_path = Path(args.graph) if args.graph else GRAPH_PATH
    if not graph_path.is_absolute():
        graph_path = (PROJECT_ROOT / graph_path).resolve()

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()

    try:
        html = build_graph_html(graph_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Always write the standalone HTML file
    written = write_graph_html(output_path, graph_path)
    print(f"Graph HTML written to: {written.relative_to(PROJECT_ROOT)}")

    if args.no_serve:
        return 0

    # Serve and open in browser
    serve_graph_html(
        html,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
