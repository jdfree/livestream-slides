"""Score an operator against the person's transition marks — the only measure.

    python -m slide_operator.training.score runs/<key> [--operator engine]

For every transition the person marked (from f to g at time t), find when the
operator put slide g on screen, nearest to t. Within TOLERANCE either way it is a
hit; otherwise it was late or early by that much, or g was never shown at all.
Notes are not scored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import marks as marks_mod

TOLERANCE = 2.0


def score(marks: list[dict], moves: list[dict]) -> dict:
    rows = []
    for m in marks_mod.transitions(marks):
        cand = [mv for mv in moves if mv["to"] == m["to"]]
        near = min(cand, key=lambda mv: abs(mv["t"] - m["t"]), default=None)
        err = None if near is None else round(near["t"] - m["t"], 1)
        rows.append({"t": m["t"], "from": m["from"], "to": m["to"], "error": err,
                     "ok": err is not None and abs(err) <= TOLERANCE,
                     "text": m.get("text", "")})
    return {"checked": len(rows), "correct": sum(r["ok"] for r in rows),
            "late": sum(1 for r in rows if r["error"] is not None and r["error"] > TOLERANCE),
            "early": sum(1 for r in rows if r["error"] is not None and r["error"] < -TOLERANCE),
            "never": sum(1 for r in rows if r["error"] is None),
            "rows": rows}


def report(marks: list[dict], moves: list[dict]) -> dict:
    res = score(marks, moves)
    if not res["checked"]:
        print("no transition marks yet — mark this service in the harness to score it")
        return res
    mm = lambda t: f"{int(t // 60):2d}:{t % 60:04.1f}"
    print(f"against your transition marks: {res['correct']}/{res['checked']}"
          f"   late {res['late']}  early {res['early']}  never shown {res['never']}")
    for r in res["rows"]:
        if r["ok"]:
            continue
        err = "never shown" if r["error"] is None else f"{r['error']:+.1f}s"
        print(f"  MISS {mm(r['t'])}  {r['from']:>2} -> {r['to']:<2} {err:>12}   {r['text'][:50]}")
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    run = Path(args[0])
    name = args[args.index("--operator") + 1] if "--operator" in args else "engine"
    dec = run / ("decisions.json" if name == "engine" else f"decisions.{name}.json")
    report(marks_mod.load(run), json.loads(dec.read_text())["moves"])
