"""What a person said about one operator's run, from that service's demo page.

One file per service, runs/<key>/feedback.json:

    {"t": 612.0, "operator": "engine", "showing": 15, "text": "moved before the amen"}

Feedback is not a label — marks.json holds those. It is a comment on what one
operator did, so it names the operator and the slide that operator had on screen
at t: a later run of the same operator may show something else there.
"""
from __future__ import annotations

import json
from pathlib import Path

KEYS = {"t", "operator", "showing", "text"}


def load(run: Path) -> list[dict]:
    p = run / "feedback.json"
    return sorted(json.loads(p.read_text()), key=lambda f: f["t"]) if p.exists() else []


def save(run: Path, items: list[dict]) -> None:
    rows = [{k: ({**f, "t": round(float(f["t"]), 1)})[k] for k in ("t", "operator", "showing", "text") if k in f}
            for f in sorted(items, key=lambda f: f["t"])]
    (run / "feedback.json").write_text(json.dumps(rows, indent=2) + "\n")


def problems(items) -> list[str]:
    """Why this is not a valid feedback file; empty when it is."""
    if not isinstance(items, list):
        return ["not a list"]
    out = []
    for i, f in enumerate(items):
        where = f"record {i}"
        if not isinstance(f, dict):
            out.append(f"{where}: not an object")
            continue
        t = f.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
            out.append(f"{where}: t must be a non-negative number")
        if not isinstance(f.get("operator"), str) or not f["operator"]:
            out.append(f"{where}: operator must be named")
        if not isinstance(f.get("text"), str) or not f["text"].strip():
            out.append(f"{where}: feedback needs text")
        s = f.get("showing")
        if "showing" in f and (not isinstance(s, int) or isinstance(s, bool)):
            out.append(f"{where}: showing must be a slide number")
        if set(f) - KEYS:
            out.append(f"{where}: unexpected fields {sorted(set(f) - KEYS)}")
    return out
