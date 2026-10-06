"""Serve the bundles, take the person's marks back, and build new bundles.

    python -m slide_operator.replay.serve [port]

    /                     the list of services
    /intake/              a form that builds a bundle for a new service
    /<date>/review/       the marking harness
    PUT /<date>/marks.json    save marks (shape-checked by training/marks.py)
    POST /api/ingest      start building a bundle; GET /api/jobs/<id> to follow it

Deliberately narrow: one writable file per bundle, a size cap, a shape check, and
one ingest at a time. It is a local tool bound to 127.0.0.1, not a service.
"""
from __future__ import annotations

import json
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..training import marks as marks_mod, web

ROOT = Path(__file__).resolve().parents[2] / "runs"
WRITABLE = re.compile(r"^/(\d{4}-\d{2}-\d{2})/marks\.json$")
MAX_BODY = 1 << 20


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(ROOT), **kw)

    def _send(self, code: int, body: str, kind: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.send_error(413, "bad body length")
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            self.send_error(400, "not json")
            return None

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, web.index_page(ROOT))
        if path in ("/intake", "/intake/"):
            return self._send(200, web.intake_page())
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", path)
        if m:
            return self._json(*web.status(m.group(1)))
        return super().do_GET()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/ingest":
            return self.send_error(404, "unknown endpoint")
        req = self._body()
        if req is None:
            return
        if not isinstance(req, dict):
            return self._json(400, {"error": "expected an object"})
        self._json(*web.start(req))

    def do_PUT(self) -> None:
        m = WRITABLE.match(self.path)
        if not m:
            self.send_error(404, "only <date>/marks.json is writable")
            return
        run = ROOT / m.group(1)
        if not run.is_dir():
            self.send_error(404, "no such bundle")
            return
        data = self._body()
        if data is None:
            return
        # The person's marks are the one thing here that cannot be regenerated.
        # Refuse anything that is not the shape the scorer and trainers read,
        # rather than overwrite them with something unreadable.
        bad = marks_mod.problems(data)
        if bad:
            self.send_error(422, "; ".join(bad[:3]))
            return
        marks_mod.save(run, data)
        self.send_response(204)
        self.end_headers()

    def end_headers(self) -> None:
        # Pages are rebuilt often; a cached copy hides the run you just marked.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args) -> None:
        # Quiet for the static traffic that dominates, but never inspect args to
        # decide: when send_error logs, its first argument is an int status code,
        # and raising here kills the connection before the status is ever sent.
        if self.command in ("PUT", "POST"):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    print(f"serving {ROOT} on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
