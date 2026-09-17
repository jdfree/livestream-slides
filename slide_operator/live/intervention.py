"""Manual intervention (SLIDE_OPERATOR.md §8).

A human at the keyboard is the strongest signal there is. What they did tells you
what they meant, and the two cases differ:

  * **They advanced** — they agree the service has moved on and were simply
    faster. Take their slide and resume normally, at once.
  * **They went back** — they are saying you were ahead. Stop acting until
    ``MANUAL_HOLD`` has passed or a human advances, whichever comes first.

Detection needs the deck to report what is actually displayed; there is no other
way to know a person touched it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import GUARDS


@dataclass
class Intervention:
    """Tracks who last moved the deck and whether we are allowed to act."""

    expected: int                      # where we believe we put it
    hold_until: float = 0.0            # we may not act before this time
    log: list[dict] = field(default_factory=list)

    def observe(self, actual: int | None, now: float) -> str | None:
        """Compare the deck against what we last commanded. Returns an event name."""
        if actual is None or actual == self.expected:
            return None
        event = "human_advanced" if actual > self.expected else "human_reversed"
        if event == "human_advanced":
            # They agree the service moved on: adopt and carry on immediately.
            self.hold_until = 0.0
        else:
            self.hold_until = now + GUARDS["MANUAL_HOLD"]
        self.log.append({"t": round(now, 2), "event": event,
                         "from": self.expected, "to": actual})
        self.expected = actual
        return event

    def may_act(self, now: float) -> bool:
        return now >= self.hold_until

    def commanded(self, index: int) -> None:
        """Record a move we made, so the next poll does not read it as a human."""
        self.expected = index
