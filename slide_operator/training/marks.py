"""The training labels: what a person said should happen, and when.

One file per service, runs/<key>/marks.json, holding two kinds of record:

    {"t": 488.4, "type": "transition", "from": 8, "to": 9}
    {"t": 503.0, "type": "note", "text": "refrain repeats here", "slide": 9}

A transition is the label: at t the deck should leave slide `from` and show slide
`to`. It is deliberately nothing more, so it can be used directly for training and
scoring. One converted from an older mark may also carry `text` — the person's
original words — which nothing scores.

A note is free text pinned to a moment and to the slide on screen then. Notes are
for people, and for operators that read context; nothing scores them.

    python -m slide_operator.training.marks convert runs/<key>   # from verdicts.json
    python -m slide_operator.training.marks check   runs/<key>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TRANSITION_KEYS = {"t", "type", "from", "to", "text"}
NOTE_KEYS = {"t", "type", "text", "slide"}


def load(run: Path) -> list[dict]:
    p = run / "marks.json"
    return sorted(json.loads(p.read_text()), key=lambda m: m["t"]) if p.exists() else []


KEY_ORDER = ("t", "type", "from", "to", "slide", "text")


def _canonical(m: dict) -> dict:
    """One spelling per record, whoever wrote it. A browser sends 351 where Python
    wrote 351.0, and reorders nothing but may; without this every save from the
    harness rewrote lines whose values had not changed, burying real edits to a
    committed training file in noise."""
    m = {**m, "t": round(float(m["t"]), 1)}
    return {k: m[k] for k in sorted(m, key=lambda k: KEY_ORDER.index(k) if k in KEY_ORDER else 99)}


def save(run: Path, marks: list[dict]) -> None:
    (run / "marks.json").write_text(
        json.dumps([_canonical(m) for m in sorted(marks, key=lambda m: m["t"])], indent=2) + "\n")


def problems(marks) -> list[str]:
    """Why this is not a valid marks file; empty when it is."""
    if not isinstance(marks, list):
        return ["not a list"]
    out = []
    for i, m in enumerate(marks):
        where = f"record {i}"
        if not isinstance(m, dict):
            out.append(f"{where}: not an object")
            continue
        t = m.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
            out.append(f"{where}: t must be a non-negative number")
        kind = m.get("type")
        if kind == "transition":
            extra = set(m) - TRANSITION_KEYS
            for k in ("from", "to"):
                v = m.get(k)
                if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                    out.append(f"{where}: {k} must be a slide number")
            if m.get("from") == m.get("to"):
                out.append(f"{where}: from and to are the same slide")
            if "text" in m and not isinstance(m["text"], str):
                out.append(f"{where}: text must be a string")
        elif kind == "note":
            extra = set(m) - NOTE_KEYS
            if not isinstance(m.get("text"), str) or not m["text"].strip():
                out.append(f"{where}: a note needs text")
            if "slide" in m and (not isinstance(m["slide"], int) or isinstance(m["slide"], bool)):
                out.append(f"{where}: slide must be a slide number")
        else:
            out.append(f"{where}: type must be 'transition' or 'note'")
            continue
        if extra:
            out.append(f"{where}: unexpected fields {sorted(extra)}")
    return out


def transitions(marks: list[dict]) -> list[dict]:
    return sorted((m for m in marks if m["type"] == "transition"), key=lambda m: m["t"])


def on_screen(marks: list[dict], t: float, first: int = 1) -> int:
    """The slide the person's own marks put on screen at time t."""
    shown = first
    for m in transitions(marks):
        if m["t"] > t:
            break
        shown = m["to"]
    return shown


# --- converting the older format -------------------------------------------
#
# verdicts.json recorded {t, to_slide, note}: "at t, this slide belongs on
# screen". Its slide picker defaulted to whatever the ENGINE was showing, so on
# September 20 the recorded slide often disagrees with the comment — "Transition
# from 51 to 52 now" filed against slide 51. The comment is what the person meant,
# so it wins whenever it names a pair.

# "verse 3->4" names verses, not slides: September 13 had "hymn 319 verse 3->4 was
# good" filed against slide 27, and reading it as a slide pair turned it into 3->4.
PAIR = re.compile(r"(?<!verse )(?<!verses )\b(\d+)\s*(?:to|->|→)\s*(\d+)", re.I)
END_OF = re.compile(r"\bend of (?:slide\s+)?(\d+)", re.I)
HOLD = re.compile(r"\b(stay|stays|not ended|has not ended|barely|don'?t transition|"
                  r"should not transition|until finished|still significant|before moving)\b", re.I)
TOO_EARLY = re.compile(r"\b(?:too|far too|way too)\s+early\b", re.I)
NOW = re.compile(r"\bnow\b", re.I)


def _is_hold(text: str) -> bool:
    """A complaint that the deck moved too soon, or a request to wait — not a
    statement that a transition happens here."""
    return bool(HOLD.search(text) or (TOO_EARLY.search(text) and not NOW.search(text)))


def from_verdicts(old: list[dict]) -> tuple[list[dict], list[str]]:
    marks, report, used = [], [], set()
    mm = lambda t: f"{int(t) // 60}:{t % 60:04.1f}"
    for v in sorted(old, key=lambda v: v["t"]):
        t, slide = round(float(v["t"]), 1), int(v["to_slide"])
        text = (v.get("note") or "").strip()
        if _is_hold(text):
            marks.append({"t": t, "type": "note", "text": text, "slide": slide})
            report.append(f"{mm(t):>8}  note        slide {slide:<3} {text[:60]}")
            continue
        flag = ""
        p, e = PAIR.search(text), END_OF.search(text)
        if p:
            f, g = int(p.group(1)), int(p.group(2))
            how = "comment"
            if g != slide:
                flag = f"  <- comment says {f}->{g}; the picker had recorded slide {slide}"
        elif e and int(e.group(1)) + 1 == slide:
            f, g, how = int(e.group(1)), slide, "comment"
        else:
            f, g, how = slide - 1, slide, "assumed"
            if e:
                flag = f"  <- comment says 'end of {e.group(1)}' but slide {slide} was recorded"
        if (f, g) in used:
            marks.append({"t": t, "type": "note", "text": f"[a second {f}->{g} mark] {text}", "slide": g})
            report.append(f"{mm(t):>8}  note        {f}->{g} repeated; kept the earlier one  {text[:40]}")
            continue
        used.add((f, g))
        rec = {"t": t, "type": "transition", "from": f, "to": g}
        if text:
            rec["text"] = text
        marks.append(rec)
        report.append(f"{mm(t):>8}  transition  {f:>3} -> {g:<3} ({how}) {text[:44]}{flag}")
    return marks, report


def _main(argv: list[str]) -> None:
    cmd, run = argv[0], Path(argv[1])
    if cmd == "convert":
        if (run / "marks.json").exists() and "--force" not in argv:
            raise SystemExit(f"{run}/marks.json exists; pass --force to overwrite it")
        marks, report = from_verdicts(json.loads((run / "verdicts.json").read_text()))
        bad = problems(marks)
        if bad:
            raise SystemExit("conversion produced an invalid file:\n  " + "\n  ".join(bad))
        save(run, marks)
        print("\n".join(report))
        n = sum(1 for m in marks if m["type"] == "transition")
        print(f"\n{len(marks)} marks: {n} transitions, {len(marks) - n} notes -> {run}/marks.json")
    elif cmd == "check":
        bad = problems(json.loads((run / "marks.json").read_text()))
        print("\n".join(bad) if bad else "ok")
    else:
        raise SystemExit("usage: python -m slide_operator.training.marks {convert|check} runs/<key>")


if __name__ == "__main__":
    _main(sys.argv[1:])
