"""Replay a bundle to an operator, strictly in time order.

    python -m slide_operator.training.runner runs/<date> [--operator engine] [--latency 1.5]

The runner owns the clock. Every TICK it hands the operator only what has become
knowable since the last call: each transcribed word at the moment a streaming
recogniser would have committed it (its end plus LATENCY), and each audio frame's
level once the frame has finished. Nothing later is reachable through step().

The result goes to runs/<date>/decisions.json for the default operator and to
decisions.<name>.json for any other, stamped with the operator's name and any
foresight it declared.
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

DEFAULT = "engine"


def run(op, run_dir: Path, latency: float = LATENCY) -> dict:
    pre = preread(run_dir)
    op.prepare(pre, foresight(run_dir) if op.foresight else None)
    raw = [json.loads(l) for l in open(run_dir / "words.jsonl")]
    words = sorted((Word(w["end"] + latency, w["start"], w["end"], w["w"], w.get("p", 0.0))
                    for w in raw), key=lambda w: (w.at, w.text))
    db, step = music_mod._envelope(run_dir / "audio.wav")[:2]
    levels = [Level((i + 1) * step, float(x)) for i, x in enumerate(db)]
    valid = {s.index for s in pre.slides}
    end = (words[-1].at if words else 0) + 60
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
    return {"operator": op.name, "foresight": list(op.foresight),
            "latency": latency, "moves": moves}


def main(run_dir: Path, name: str = DEFAULT, latency: float = LATENCY) -> dict:
    res = run(get(name), run_dir, latency)
    out = run_dir / ("decisions.json" if name == DEFAULT else f"decisions.{name}.json")
    out.write_text(json.dumps(res, indent=2))
    mm = lambda t: f"{int(t // 60):2d}:{int(t % 60):02d}"
    titles = {s.index: s.title for s in preread(run_dir).slides}
    for m in res["moves"]:
        print(f"{mm(m['t'])}  {m['from']:>2} -> {m['to']:<2} {titles.get(m['to'], '')[:28]:<28} {m['rule']}")
    if res["foresight"]:
        print("\nNOT LIVE-VALID — this operator used foresight:")
        for f in res["foresight"]:
            print(f"  - {f}")
    print()
    score_mod.report(marks_mod.load(run_dir), res["moves"])
    print(f"\nwrote {out}")
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args[args.index("--operator") + 1] if "--operator" in args else DEFAULT
    lat = float(args[args.index("--latency") + 1]) if "--latency" in args else LATENCY
    main(Path(args[0]), name, lat)
