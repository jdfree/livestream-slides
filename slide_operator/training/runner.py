"""Replay a bundle to an operator, strictly in time order.

    python -m slide_operator.training.runner runs/<key> [--operator ML1] [--latency 1.5] [--until SECONDS]

The runner owns the clock. Every TICK it hands the operator only what has become
knowable since the last call: each transcribed word at the moment a streaming
recogniser would have committed it (its end plus LATENCY), and each audio frame's
level once the frame has finished. Nothing later is reachable through step().

The result goes to runs/<key>/decisions.json for the default operator and to
decisions.<name>.json for any other, stamped with the operator's name and any
foresight it declared, and with whatever usage the operator reports (calls, cost,
response times). --until stops the replay early, and the score then covers only
the marks before that moment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..audio import music as music_mod
from ..replay.run import LATENCY, TICK
from . import marks as marks_mod, score as score_mod
from .operator import Level, Word, foresight, preread
from .operators import get

DEFAULT = "ML1"


def run(op, run_dir: Path, latency: float = LATENCY, until: float | None = None) -> dict:
    pre = preread(run_dir)
    op.prepare(pre, foresight(run_dir) if op.foresight else None)
    raw = [json.loads(l) for l in open(run_dir / "words.jsonl")]
    words = sorted((Word(w["end"] + latency, w["start"], w["end"], w["w"], w.get("p", 0.0))
                    for w in raw), key=lambda w: (w.at, w.text))
    db, step = music_mod._envelope(run_dir / "audio.wav")[:2]
    levels = [Level((i + 1) * step, float(x)) for i, x in enumerate(db)]
    valid = {s.index for s in pre.slides}
    end = (words[-1].at if words else 0) + 60
    if until is not None:
        end = min(end, until)
    cur, moves = pre.slides[0].index, []
    i = j = 0
    t = 0.0
    while t < end:
        nw, nl = [], []
        while i < len(words) and words[i].at <= t:
            nw.append(words[i]); i += 1
        while j < len(levels) and levels[j].at <= t:
            nl.append(levels[j]); j += 1
        for d in op.step(t, nw, nl):
            if d.to != cur and d.to in valid:
                moves.append({"t": round(d.at, 2), "from": cur, "to": d.to,
                              "rule": d.why, "heard": d.heard})
                cur = d.to
        t += TICK
    res = {"operator": op.name, "foresight": list(op.foresight), "latency": latency, "moves": moves}
    if until is not None:
        res["until"] = until
    if hasattr(op, "stats"):
        res["stats"] = op.stats()
    return res


def decisions_path(run_dir: Path, name: str = DEFAULT) -> Path:
    return run_dir / ("decisions.json" if name == DEFAULT else f"decisions.{name}.json")


def main(run_dir: Path, name: str = DEFAULT, latency: float = LATENCY, until: float | None = None) -> dict:
    res = run(get(name), run_dir, latency, until)
    out = decisions_path(run_dir, name)
    out.write_text(json.dumps(res, indent=2))
    mm = lambda t: f"{int(t // 60):2d}:{int(t % 60):02d}"
    titles = {s.index: s.title for s in preread(run_dir).slides}
    for m in res["moves"]:
        print(f"{mm(m['t'])}  {m['from']:>2} -> {m['to']:<2} {titles.get(m['to'], '')[:28]:<28} {m['rule']}")
    if res["foresight"]:
        print("\nNOT LIVE-VALID — this operator used foresight:")
        for f in res["foresight"]:
            print(f"  - {f}")
    if res.get("stats"):
        print("\n" + "  ".join(f"{k} {v}" for k, v in res["stats"].items()))
    print()
    marks = marks_mod.load(run_dir)
    if until is not None:
        marks = [m for m in marks if m["t"] <= until]
        print(f"(replayed to {until / 60:.1f} min; scoring the {len(marks)} marks before then)")
    score_mod.report(marks, res["moves"])
    print(f"\nwrote {out}")
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args[args.index("--operator") + 1] if "--operator" in args else DEFAULT
    lat = float(args[args.index("--latency") + 1]) if "--latency" in args else LATENCY
    until = float(args[args.index("--until") + 1]) if "--until" in args else None
    main(Path(args[0]), name, lat, until)
