"""ML1: the first version — machine-learning models to hear and read, hand-written
rules (the engine in replay/run.py) to decide. As an operator.

It is not live-valid. Its sung-slide rules lean on a music map and a lyric/note
alignment computed over the whole recording, so it declares both as foresight.
Until those are rebuilt incrementally from audio heard so far, its scores
overstate what it would do in a live service.
"""
from __future__ import annotations

from ...replay.run import Engine
from ..operator import Decision, Foresight, PreRead


class ML1Operator:
    name = "ML1"
    foresight = ("music map computed over the whole recording",
                 "lyric and note alignment computed over the whole recording")

    def prepare(self, pre: PreRead, foresight: Foresight | None) -> None:
        self.eng = Engine(pre.slides, foresight.music, foresight.aligned)
        self.seen = 0

    def step(self, t, words, levels):
        for w in words:
            self.eng.hear(w.at, w.text)
        self.eng.tick(t)
        new = self.eng.moves[self.seen:]
        self.seen = len(self.eng.moves)
        return [Decision(m["t"], m["to"], m["rule"], m["heard"]) for m in new]
