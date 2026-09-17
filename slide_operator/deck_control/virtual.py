"""A deck that exists only in memory, for replay and for testing §8.

A recording carries no record of anyone touching the keyboard, so interventions
have to be injected: schedule a change the engine did not ask for and check that
it notices, adopts the new position, and holds off as §8 requires.
"""
from __future__ import annotations


class VirtualDeck:
    def __init__(self, total: int, start: int = 1):
        self._total = total
        self._slide = start
        self.commands: list[tuple[float, int]] = []   # (when, index) we issued
        self._scripted: list[tuple[float, int]] = []  # (when, index) a human does

    def schedule_human(self, when: float, index: int) -> None:
        self._scripted.append((when, index))
        self._scripted.sort()

    def tick(self, now: float) -> None:
        """Apply any human change whose moment has arrived."""
        while self._scripted and self._scripted[0][0] <= now:
            _, index = self._scripted.pop(0)
            self._slide = index

    def current_slide(self) -> int | None:
        return self._slide

    def goto(self, index: int, now: float = 0.0) -> bool:
        if not 1 <= index <= self._total:
            return False
        self._slide = index
        self.commands.append((now, index))
        return True

    def total(self) -> int:
        return self._total
