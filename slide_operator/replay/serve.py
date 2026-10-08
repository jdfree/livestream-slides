"""Serve the bundles, take the person's marks back, and build new bundles.

    python -m slide_operator.replay.serve [port]

    /                         the list of services
    /intake/                  a form that builds (or replaces) a service's bundle
    /<key>/review/            the marking harness
    /<key>/demo/?op=<name>    an operator's run against the marks
    GET|PUT /<key>/marks.json      the marks (shape-checked by training/marks.py)
    GET|PUT /<key>/feedback.json   feedback on operator runs (training/feedback.py)
    POST /api/ingest          build a bundle; POST /api/run replays an operator;
                              GET /api/jobs/<id> follows either

<key> is the service's date and location, e.g. 2026-09-20-st-peter-fort-collins.

Deliberately narrow: two writable files per bundle, a size cap, a shape check, and
one job at a time. A save must name the version it was made from (If-Match, from
the ETag of the GET): a page opened before someone else's save would otherwise
write its stale copy over that save. It is a local tool bound to 127.0.0.1.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..training import feedback as feedback_mod, marks as marks_mod, web
from ..training.ingest import KEY, WRITE_LOCK
from ..training.operators import OPERATORS
from ..training.runner import DEFAULT

ROOT = Path(__file__).resolve().parents[2] / "runs"
WRITABLE = re.compile(rf"^/({KEY})/(marks|feedback)\.json$")
DEMO = re.compile(rf"^/({KEY})/demo/?$")
CHECK = {"marks": marks_mod, "feedback": feedback_mod}
MAX_BODY = 1 << 20


def etag(p: Path) -> str:
    return '"' + hashlib.sha1(p.read_bytes() if p.exists() else b"").hexdigest()[:16] + '"'


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(ROOT), **kw)

    def _send(self, code: int, body: str, kind: str = "text/html; charset=utf-8", headers=()) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            self.send_header(k, v)
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
        path, _, query = self.path.partition("?")
        if path == "/":
            return self._send(200, web.index_page(ROOT))
        if path in ("/intake", "/intake/"):
            return self._send(200, web.intake_page())
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", path)
        if m:
            return self._json(*web.status(m.group(1)))
        m = WRITABLE.match(path)
        if m:
            run = ROOT / m.group(1)
            if not run.is_dir():
                return self.send_error(404, "no such service")
            p = run / f"{m.group(2)}.json"
            return self._send(200, p.read_text() if p.exists() else "[]\n", "application/json",
                              [("ETag", etag(p))])
        m = DEMO.match(path)
        if m:
            if not path.endswith("/"):          # the page's relative links need the slash
                self.send_response(301)
                self.send_header("Location", path + "/" + (f"?{query}" if query else ""))
                return self.end_headers()
            run = ROOT / m.group(1)
            if not (run / "deck.pptx").exists():
                return self.send_error(404, "no such service")
            op = (re.search(r"(?:^|&)op=([\w-]+)", query) or [None, DEFAULT])[1]
            if op not in OPERATORS:
                return self.send_error(404, f"no operator {op!r}")
            from . import site
            return self._send(200, site.demo_page(run, op, etag(run / "feedback.json")))
        return super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/api/ingest", "/api/run"):
            return self.send_error(404, "unknown endpoint")
        req = self._body()
        if req is None:
            return
        if not isinstance(req, dict):
            return self._json(400, {"error": "expected an object"})
        self._json(*(web.start(req) if path == "/api/ingest" else web.start_run(req)))

    def do_PUT(self) -> None:
        m = WRITABLE.match(self.path)
        if not m:
            return self.send_error(404, "only <key>/marks.json and <key>/feedback.json are writable")
        run, kind = ROOT / m.group(1), m.group(2)
        if not run.is_dir():
            return self.send_error(404, "no such service")
        data = self._body()
        if data is None:
            return
        # The person's marks are the one thing here that cannot be regenerated.
        # Refuse anything that is not the shape the scorer and trainers read,
        # rather than overwrite them with something unreadable.
        bad = CHECK[kind].problems(data)
        if bad:
            return self.send_error(422, "; ".join(bad[:3]))
        with WRITE_LOCK:
            p = run / f"{kind}.json"
            if self.headers.get("If-Match") != etag(p):
                return self.send_error(409 if self.headers.get("If-Match") else 428,
                                       "changed since this page loaded it; reload the page")
            CHECK[kind].save(run, data)
            self.send_response(204)
            self.send_header("ETag", etag(p))
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
