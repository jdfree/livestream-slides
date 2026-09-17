"""PowerPoint on macOS, driven by AppleScript.

PowerPoint reports the slide it is actually showing, which is what makes §8
possible: if that index changes and we did not ask for it, a human did.

Vocabulary taken from PowerPoint's own scripting dictionary, not guessed:

  * the window's property is ``slideshow view`` — one word;
  * ``current show position`` is **read only**, so a slide is changed with the
    ``go to slide`` command and never by assigning to that property;
  * ``go to slide`` takes the view and a required ``number``.
"""
from __future__ import annotations

import subprocess

TIMEOUT = 5.0
APP = "Microsoft PowerPoint"

_READ = [
    "get current show position of slideshow view of slide show window 1",
    "get slide index of slide of slideshow view of slide show window 1",
    "get current show position of slide show view of slide show window 1",
]
_GOTO = [
    "go to slide (slideshow view of slide show window 1) number %d",
    "go to slide (slide show view of slide show window 1) number %d",
]
_SHOWING = "get count of slide show windows"
_TOTAL = "get count of slides of active presentation"


def _osa(body: str) -> str | None:
    try:
        r = subprocess.run(["osascript", "-e", f'tell application "{APP}" to {body}'],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


class PowerPointDeck:
    """Live deck. Remembers which spelling this version of PowerPoint answers to."""

    def __init__(self) -> None:
        self._read: str | None = None
        self._goto: str | None = None

    def is_presenting(self) -> bool:
        out = _osa(_SHOWING)
        return bool(out and out.isdigit() and int(out) > 0)

    def current_slide(self) -> int | None:
        for s in ([self._read] if self._read else _READ):
            out = _osa(s)
            if out and out.lstrip("-").isdigit():
                self._read = s
                return int(out)
        return None

    def goto(self, index: int) -> bool:
        for s in ([self._goto] if self._goto else _GOTO):
            if _osa(s % index) is not None:
                self._goto = s
                return self.current_slide() == index
        return False

    def total(self) -> int:
        out = _osa(_TOTAL)
        return int(out) if out and out.isdigit() else 0


if __name__ == "__main__":
    d = PowerPointDeck()
    print("PowerPoint version :", _osa("get version") or "no answer")
    print("presentations open :", _osa("get count of presentations") or "-")
    print("slides in deck     :", d.total())
    print("presenting now     :", d.is_presenting())
    print("slide on screen    :", d.current_slide())
    if not d.is_presenting():
        print("\nStart a slide show (⌘⇧⏎ in PowerPoint), then run this again:")
        print("  python3 -m slide_operator.deck_control.powerpoint")
