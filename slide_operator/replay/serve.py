"""Serve the run directories, and take the human's judgments back.

    python -m slide_operator.replay.serve [port]

A plain static server cannot accept anything, so the review page could only ever
put a judgment on the clipboard. This serves runs/ read-only exactly as before and
additionally accepts PUT /<run>/verdicts.json, writing it into that run directory
where verdicts.py already knows how to score it.

Deliberately narrow: one writable path per run, a size cap, and a shape check. It
is a local review tool, not a service.
"""
from __future__ import annotations

import json
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "runs"
WRITABLE = re.compile(r"^/(\d{4}-\d{2}-\d{2})/verdicts\.json$")
MAX_BODY = 1 << 20
FIELDS = {"t", "to_slide", "note", "kind"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(ROOT), **kw)

    def do_PUT(self) -> None:
        m = WRITABLE.match(self.path)
        if not m:
            self.send_error(404, "only <run>/verdicts.json is writable")
            return
        run = ROOT / m.group(1)
        if not run.is_dir():
            self.send_error(404, "no such run")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.send_error(413, "bad body length")
            return
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self.send_error(400, "not json")
            return
        # The human record is the one piece of evidence here that is not machine
        # made. Refuse anything that is not the shape verdicts.py reads, rather
        # than overwrite it with something unreadable.
        if not isinstance(data, list) or not all(
                isinstance(v, dict) and FIELDS.issuperset(v) and "t" in v for v in data):
            self.send_error(422, "not a verdict list")
            return
        (run / "verdicts.json").write_text(json.dumps(data, indent=2))
        self.send_response(204)
        self.end_headers()

    def end_headers(self) -> None:
        # The page is rebuilt often; a cached copy hides the run you just scored.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args) -> None:
        # Quiet for the static traffic that dominates, but never inspect args to
        # decide: when send_error logs, its first argument is an int status code,
        # and raising here kills the connection before the status is ever sent —
        # so every refusal arrived as a dropped socket instead of a 400.
        if self.command == "PUT":
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    print(f"serving {ROOT} on http://localhost:{port}  (PUT <run>/verdicts.json to save)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
