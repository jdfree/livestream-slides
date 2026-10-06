"""What an operator may know, and when it may know it.

An operator decides when the deck should move. Anything can be one — the
hand-written engine, Claude, another model — provided it accepts two calls and
never looks further ahead than it is shown:

    prepare(pre, foresight)     everything that can be read before the service
    step(t, words, levels)      everything heard up to time t, and nothing after

Pre-reading is allowed and is the point: the slides, the lyrics OCR'd from their
sheet music, the notes recognised on their staves, the bulletin, how the bulletin
and deck correlate, and the operating instructions accumulated in SLIDE_OPERATOR.md
are all known before anyone sings a note. The audio is not.

Foresight. The original engine reads a music map and a lyric/note alignment that
were computed over the whole recording before replay began — knowledge of the
future that a live system cannot have. An operator that needs such inputs must
name them in `foresight`; the runner then hands them over through a separate,
clearly labelled argument and stamps every result as not live-valid. An operator
that names nothing receives None there.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..ingest import deck as deck_mod, folder as folder_mod, melody

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Word:
    at: float       # when a live recogniser would have committed it: end + latency
    start: float
    end: float
    text: str
    p: float


@dataclass(frozen=True)
class Level:
    at: float       # end of the audio frame, when its level is first knowable
    db: float


@dataclass(frozen=True)
class Decision:
    at: float
    to: int
    why: str
    heard: str = ""


@dataclass
class PreRead:
    run: Path
    slides: list                      # ingest.deck.Slide, lyrics attached
    bulletin: list[str]               # the worship folder, block by block
    service_map: dict | None          # folder <-> deck correlation (prepare)
    instructions: str                 # SLIDE_OPERATOR.md
    staves: dict = field(default_factory=dict)   # slide -> recognised pitch classes

    def slide_table(self) -> list[dict]:
        """The deck as plain data, for operators that read text."""
        return [{"index": s.index, "title": s.title, "body": s.body, "lyrics": s.lyrics,
                 "cover": s.is_cover, "sung": s.musical, "element": s.run_id,
                 "staves": self.staves.get(str(s.index), [])} for s in self.slides]


@dataclass
class Foresight:
    music: dict           # music map over the WHOLE recording (audio.music.analyze)
    aligned: dict         # lyric + note alignment over the WHOLE recording


class Operator(Protocol):
    name: str
    foresight: tuple[str, ...]

    def prepare(self, pre: PreRead, foresight: Foresight | None) -> None: ...

    def step(self, t: float, words: list[Word], levels: list[Level]) -> list[Decision]: ...


def preread(run: Path) -> PreRead:
    slides = deck_mod.load(run / "deck.pptx")
    melody.attach(slides, run / "deck.pptx", run / "lyrics.json")
    bulletin_path = next((run / f"folder{x}" for x in (".pdf", ".docx")
                          if (run / f"folder{x}").exists()), None)
    bulletin = [b.text for b in folder_mod.load(bulletin_path)] if bulletin_path else []
    sm = run / "service_map.json"
    staves = run / "notes.json"
    return PreRead(run=run, slides=slides, bulletin=bulletin,
                   service_map=json.loads(sm.read_text()) if sm.exists() else None,
                   instructions=(REPO / "SLIDE_OPERATOR.md").read_text(),
                   staves=json.loads(staves.read_text()) if staves.exists() else {})


def foresight(run: Path) -> Foresight:
    from ..audio import music as music_mod
    aligned = {}
    for name in ("align.json", "note_align.json"):
        p = run / name
        if p.exists():
            aligned.update({int(k): v for k, v in json.loads(p.read_text()).items()})
    return Foresight(music=music_mod.analyze(run), aligned=aligned)
