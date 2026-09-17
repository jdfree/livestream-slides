"""The live loop: audio in, slides out, every decision visible.

One pass of `step()` does what a human operator does continuously — look at what
is on screen, listen to what just happened, decide whether to move, and move.

The deck is polled every pass because that is the only way to notice a person
taking over (§8). Everything the loop knows is published as a state snapshot, so
the HUD shows the operator exactly the inputs the engine acted on.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..audio import music as music_mod
from ..config import GUARDS
from ..ingest import deck as deck_mod, melody
from ..live.intervention import Intervention
from ..replay.run import Engine

POLL = 0.5          # how often the deck is asked what it is showing
TICK = 0.25
LEVEL_WINDOW = 1.0


@dataclass
class State:
    t: float = 0.0
    slide: int = 1
    actual: int | None = None
    total: int = 0
    presenting: bool = False
    holding: bool = False
    hold_until: float = 0.0
    level_db: float = -99.0
    music: bool = False
    voice: str = "-"
    heard: str = ""
    decisions: list[dict] = field(default_factory=list)
    interventions: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.time)


class Harness:
    def __init__(self, run: Path, deck, capture, asr=None, hud=None):
        # not `self.run`: that would shadow the run() method below
        self.run_dir, self.deck, self.capture = run, deck, capture
        self.asr, self.hud = asr, hud
        self.slides = deck_mod.load(run / "deck.pptx")
        melody.attach(self.slides, run / "deck.pptx", run / "lyrics.json")

        # Analysis that exists before the service: the music map from a rehearsal
        # recording, the aligned words and notes. Live, these fill in as the
        # service runs; absent, the engine falls back to its word rules.
        music = music_mod.analyze(run) if (run / "music.json").exists() else None
        aligned: dict = {}
        for name in ("align.json", "note_align.json"):
            p = run / name
            if p.exists():
                aligned.update({int(k): v for k, v in json.loads(p.read_text()).items()})
        self.engine = Engine(self.slides, music, aligned)
        self.voices = self._load_voices(run)

        self.state = State(slide=self.engine.cur, total=len(self.slides))
        self.iv = Intervention(expected=self.engine.cur)
        self._last_poll = -1e9
        self._pushed = 0   # engine moves already sent to the deck

    @staticmethod
    def _load_voices(run: Path) -> list[dict]:
        p = run / "voices.json"
        return json.loads(p.read_text())["segments"] if p.exists() else []

    def _voice_at(self, t: float) -> str:
        for s in self.voices:
            if s["t0"] <= t < s["t1"]:
                return f'{s["role"]} · {s["mode"]}'
        return "-"

    def step(self) -> None:
        now = self.capture.elapsed
        st = self.state
        st.t = now

        if hasattr(self.deck, "tick"):       # virtual deck: apply scripted humans
            self.deck.tick(now)

        # 1. What is actually on screen? Only this reveals a human intervention.
        if now - self._last_poll >= POLL:
            self._last_poll = now
            st.actual = self.deck.current_slide()
            st.presenting = getattr(self.deck, "is_presenting", lambda: True)()
            event = self.iv.observe(st.actual, now)
            if event:
                st.interventions.append(self.iv.log[-1])
                self.engine.cur = st.actual          # their slide is ground truth
                self.engine.last_move = now
        st.holding = not self.iv.may_act(now)
        st.hold_until = self.iv.hold_until

        # 2. What has been heard since last time?
        if self.asr and self.asr.due(now):
            for w in self.asr.feed(self.capture.buffer.tail(self.asr.window), now):
                # The engine runs on one clock. A word is handed to it at the
                # moment it becomes known, not at the moment it was spoken —
                # mixing the two makes every dwell and cooldown comparison lie.
                self.engine.hear(now, w["w"])
            st.heard = " ".join(self.engine.recent)

        # 3. Level and music, for the operator to see and the rules to use.
        tail = self.capture.buffer.tail(LEVEL_WINDOW)
        if len(tail):
            rms = float(np.sqrt(np.maximum((tail ** 2).mean(), 1e-12)))
            st.level_db = round(20 * np.log10(max(rms, 1e-6)), 1)
        st.music = self.engine._region(now) is not None
        st.voice = self._voice_at(now)

        # 4. Decide. Word-driven moves happen inside hear(); time-driven ones in
        # tick(). Both must reach the deck, so the deck is synchronised after each.
        self._sync(now)
        self.engine.tick(now)
        self._sync(now)
        st.slide = self.engine.cur

        if self.hud:
            self.hud.publish(self.snapshot())

    def _sync(self, now: float) -> None:
        """Push every move the engine has made that the deck has not yet seen."""
        while len(self.engine.moves) > self._pushed:
            move = dict(self.engine.moves[self._pushed])
            self._pushed += 1
            if not self.iv.may_act(now):
                # §8: a person moved us back. Keep listening, but do not act —
                # and put the engine back where the person left the deck.
                move["rule"] += "  (SUPPRESSED — holding after a human reversal)"
                self.engine.cur = self.iv.expected
            elif self.deck.goto(move["to"]):
                self.iv.commanded(move["to"])
            else:
                move["rule"] += "  (DECK REFUSED)"
            self.state.decisions.append(move)

    def snapshot(self) -> dict:
        st, by = self.state, {s.index: s for s in self.slides}
        def card(i):
            s = by.get(i)
            return None if not s else {
                "index": i, "title": s.title,
                "img": f"slides/{i:03d}.png",
                "text": (s.lyrics or s.body).replace("\n", " ")[:300],
                "sung": bool(s.musical), "cover": bool(s.is_cover)}
        return {
            "t": round(st.t, 1), "slide": card(st.slide), "next": card(st.slide + 1),
            "actual": st.actual, "total": st.total, "presenting": st.presenting,
            "holding": st.holding, "hold_left": max(0.0, round(st.hold_until - st.t, 1)),
            "level_db": st.level_db, "music": st.music, "voice": st.voice,
            "heard": st.heard, "guards": GUARDS,
            "decisions": st.decisions[-12:][::-1],
            "interventions": st.interventions[-6:][::-1],
        }

    def run(self, until: float | None = None) -> None:
        while until is None or self.capture.elapsed < until:
            self.step()
            time.sleep(TICK)
