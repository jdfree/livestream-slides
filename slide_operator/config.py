"""Read the operating guards out of SLIDE_OPERATOR.md.

The document is the specification; this makes it the *source*. Edit the guard
block in §6 and the engine changes behaviour — no code edit, no second copy of
the numbers to drift out of step.
"""
from __future__ import annotations

import re
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "SLIDE_OPERATOR.md"
DEFAULTS = {"MIN_DWELL": 4.0, "MIN_DWELL_HOLD": 45.0, "MAX_RATE": 4.0,
            "COOLDOWN": 2.0, "MANUAL_HOLD": 30.0}
_LINE = re.compile(r"^([A-Z][A-Z_]+)\s+([0-9]+(?:\.[0-9]+)?)\s", re.M)


def load(doc: Path | None = None) -> dict[str, float]:
    text = (doc or DOC).read_text()
    found = dict(DEFAULTS)
    for block in re.findall(r"```\n(.*?)```", text, re.S):
        if "MIN_DWELL" not in block:
            continue
        for name, value in _LINE.findall(block):
            found[name] = float(value)
    return found


GUARDS = load()

if __name__ == "__main__":
    for k, v in load().items():
        mark = "" if v == DEFAULTS.get(k) else "   <- differs from built-in default"
        print(f"  {k:16} {v:6.1f}{mark}")
