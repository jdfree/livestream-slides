"""Human judgments of what belonged on screen. This is the evaluation.

The machine-built reference is not used: it smears identical refrains across a
hymn, lists slides out of order, and derives its sung boundaries from the same
alignment the engine reads, so agreeing with it proves nothing.

Each mark is one unambiguous fact — at time t, slide to_slide belonged on screen.
That single form covers both things a person wants to say:

    "change here"  mark the moment the new slide should appear
    "not yet"      mark a moment the current slide should still be up

and both are graded the same way: find the window during which the engine
actually displayed that slide, and measure how far t falls outside it.

    error > 0   the slide arrived late  (it was not up yet at t)
    error < 0   the slide left early    (it was already gone at t)

Measuring instead against "the nearest move to that slide" reads a hold mark
backwards — it reports the move INTO the slide, so a slide removed 2.8 s early
looked like a 33.8 s error and nearly sent a fix chasing a bug that wasn't there.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

TOLERANCE = 2.0          # a slide on screen within this of a stated time is correct
FOREVER = 1e9


@dataclass
class Verdict:
    t: float                 # service seconds
    to_slide: int | None     # the slide that belonged on screen then
    note: str
    kind: str = "exact"      # exact | good — both mean the same thing


def load(run: Path) -> list[Verdict]:
    p = run / "verdicts.json"
    if not p.exists():
        return []
    return [Verdict(**v) for v in json.loads(p.read_text())]


def save(run: Path, verdicts: list[Verdict]) -> None:
    (run / "verdicts.json").write_text(
        json.dumps([asdict(v) for v in verdicts], indent=2))


def shown_windows(moves: list[dict], first: int) -> list[tuple[int, float, float]]:
    """(slide, from, until) for every stretch the engine had a slide on screen."""
    out, cur, t0 = [], first, 0.0
    for m in moves:
        out.append((cur, t0, m["t"]))
        cur, t0 = m["to"], m["t"]
    out.append((cur, t0, FOREVER))
    return out


def error_for(windows, slide: int, t: float) -> float | None:
    """How far t falls outside the window this slide was on screen. None: never."""
    spans = [w for w in windows if w[0] == slide]
    if not spans:
        return None
    inside = [w for w in spans if w[1] <= t <= w[2]]
    if inside:
        return 0.0
    # nearest window, and which side of it t fell on
    w = min(spans, key=lambda w: min(abs(w[1] - t), abs(w[2] - t)))
    return round(w[1] - t, 1) if t < w[1] else round(w[2] - t, 1)


def score(run: Path, moves: list[dict], first: int) -> dict:
    windows = shown_windows(moves, first)
    rows = []
    for v in load(run):
        err = error_for(windows, v.to_slide, v.t)
        rows.append({"want": v.t, "to": v.to_slide, "note": v.note, "kind": v.kind,
                     "error": err,
                     "ok": err is not None and abs(err) <= TOLERANCE})
    hit = sum(1 for r in rows if r["ok"])
    late = [r["error"] for r in rows if r["error"] and r["error"] > TOLERANCE]
    early = [r["error"] for r in rows if r["error"] and r["error"] < -TOLERANCE]
    never = [r for r in rows if r["error"] is None]
    return {"checked": len(rows), "correct": hit, "rows": rows,
            "late": len(late), "early": len(early), "never": len(never),
            "worst": sorted(rows, key=lambda r: -abs(r["error"] or FOREVER))[:10]}


if __name__ == "__main__":
    import sys
    from ..ingest import deck as deck_mod
    run = Path(sys.argv[1])
    moves = json.loads((run / "decisions.json").read_text())["moves"]
    first = deck_mod.load(run / "deck.pptx")[0].index
    res = score(run, moves, first)
    mm = lambda t: f"{int(t//60):2d}:{t%60:04.1f}"
    print(f"against the human record: {res['correct']}/{res['checked']}"
          f"   late {res['late']}  early {res['early']}  never shown {res['never']}")
    for r in sorted(res["rows"], key=lambda r: r["want"]):
        if r["error"] is None:
            err = "never shown"
        elif r["error"] == 0:
            err = "     on screen"
        else:
            err = f"{r['error']:+7.1f}s {'late' if r['error'] > 0 else 'early'}"
        print(f"  {'OK  ' if r['ok'] else 'MISS'} {mm(r['want'])} -> {r['to']:>2} {err:>16}   {r['note'][:56]}")
