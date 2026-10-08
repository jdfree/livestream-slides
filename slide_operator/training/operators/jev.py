"""Jev: TypeSafe's decision model, asked one closed question at a time.

Jev does not write text. Given a state and a question with named choices, it
returns the choice with a calibrated probability for each, in well under a
second (https://api.typesafe.ai/openapi.json). That fits what a slide operator
decides every moment: stay on this slide, go to the next, or skip one.

So each call puts the operator's situation in `state` — the slide on screen and
the two after it, what has been heard since it went up, what the sound is doing,
and how long earlier slides of the same hymn took — and asks one choice question
whose instructions condense SLIDE_OPERATOR.md §6 (the decision table and "the
moment to advance"). The guards are §6's own: minimum dwell, cooldown, rate cap.

Live-valid by construction: no foresight, only what has been heard. It acts as a
live operator would, too — one request in flight at a time, and a decision takes
effect when its answer arrives, so Jev's own latency is charged to its timing.

Needs TYPESAFE_API_KEY (see .secrets; run under `secrets run --`).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

from ...config import GUARDS
from ..operator import Decision, Foresight, PreRead

API = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_MTOK = 0.042        # input tokens, USD, as published September 2026; output is free

MIN_GAP = 1.0                 # seconds between requests while there is news
MAX_GAP = 3.0                 # ask at least this often anyway: a hymn moves on without words
ADVANCE_AT = 0.5              # P(next) + P(skip) needed to move
LEAVE_COVER_AT = 0.8          # ...and to leave a cover slide, where patience costs nothing
LOUD_ABOVE_FLOOR = 15.0       # dB: a frame this far above the room's floor is sound, not room

INSTRUCTIONS = """You are running the slides during a live church service. The congregation reads or sings the slide on screen. Decide whether to keep it up or move on, now.

Move on when the congregation reaches the LAST words of the slide on screen — at its final phrase, not after the next slide's first words. For slides read aloud, that is when the end of its text is heard. For sung slides, it is when its final line begins; singing is poorly transcribed, so also compare the seconds this slide has been up with how long earlier slides of the same hymn took for a similar number of words.

Move onto a sung slide when music starts after spoken words have finished. Move onto a blank or title (cover) slide as soon as the previous slide's words are finished. Leave a cover slide only when the next part has begun: its own words are heard, or, if the next slide is sung, the singing has started (sustained sound after spoken words) — never because time has passed.

Showing a slide early strands people mid-sentence; showing it late is less harmful but still wrong. Skip a slide only when the words heard clearly belong to the slide after next."""

CRITERIA = {
    "stay": "Keep the slide on screen: its words are still being read or sung, or nothing yet shows the next part has begun.",
    "next": "Show the next slide now.",
    "skip": "Show the slide after next now: the next slide was passed over and its successor's words are being heard.",
}


class Jev:
    """The HTTP client: one POST per question set, timed."""

    def __init__(self, model: str | None = None):
        self.key = os.environ.get("TYPESAFE_API_KEY")
        if not self.key:
            raise SystemExit("TYPESAFE_API_KEY is not set. Store the key in Bitwarden as "
                             "'James/TypeSafe API Key' and run under `secrets run --`.")
        self.model = model or os.environ.get("JEV_MODEL", "jev-latest")

    def ask(self, state: dict, questions: dict) -> tuple[dict, float]:
        body = json.dumps({"model": self.model, "state": state, "questions": questions}).encode()
        req = urllib.request.Request(API, body, {"Authorization": f"Bearer {self.key}",
                                                 "Content-Type": "application/json"})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.load(r)
        return res, time.monotonic() - t0


def _ends_with(text: str, n: int = 10) -> str:
    return " ".join(text.split()[-n:])


class JevOperator:
    name = "Jev"
    foresight = ()
    needs = ("TYPESAFE_API_KEY",)

    def __init__(self, client=None):
        self.client = client

    # --- before the service -----------------------------------------------
    def prepare(self, pre: PreRead, foresight: Foresight | None) -> None:
        self.client = self.client or Jev()
        self.slides = pre.slides
        self.pos = {s.index: i for i, s in enumerate(pre.slides)}
        self.cur = pre.slides[0].index
        self.since = 0.0                     # when the slide on screen went up
        self.moves: list[float] = []
        self.heard: list[tuple[float, str]] = []
        self.levels: list[tuple[float, float]] = []
        self.busy_until = 0.0                # a request is in flight until then
        self.last_ask = -1e9
        self.news = False
        self.dwell: dict[int, float] = {}    # slide -> seconds it was up, for the hymn's pace
        self.stats_ = {"calls": 0, "input_tokens": 0, "errors": 0, "latency": [], "model": None}

    def _slide(self, i: int | None) -> dict | None:
        if i is None or i not in self.pos:
            return None
        s = self.slides[self.pos[i]]
        text = (s.lyrics or s.body).replace("\n", " ").strip()
        kind = ("cover: shows no words to read" if s.is_cover else
                "sung" if s.musical else "read aloud or listened to")
        out = {"slide": s.index, "title": s.title, "kind": kind, "words": len(text.split())}
        if text:
            out.update(text=text[:600], ends_with=_ends_with(text))
        return out

    def _after(self, i: int, k: int = 1) -> int | None:
        j = self.pos[i] + k
        return self.slides[j].index if j < len(self.slides) else None

    # --- what the sound is doing, from levels heard so far ------------------
    def _sound(self, t: float) -> dict:
        recent = [db for at, db in self.levels if at > t - 300]
        if len(recent) < 8:
            return {"now": "not enough heard yet"}
        floor = statistics.quantiles(recent, n=10)[0]
        loud = lambda db: db > floor + LOUD_ABOVE_FLOOR
        last4 = [db for at, db in self.levels if at > t - 4]
        share = sum(map(loud, last4)) / max(1, len(last4))
        held = quiet = 0.0
        for at, db in reversed(self.levels):          # how long the present state has lasted
            if loud(db) and not quiet:
                held = t - at
            elif not loud(db) and not held:
                quiet = t - at
            else:
                break
        words4 = sum(1 for at, _ in self.heard if at > t - 4)
        now = ("continuous sound, likely music or singing" if share > 0.9 else
               "sound with pauses, likely speech" if share > 0.3 else "quiet")
        return {"now": now, "continuous_for_seconds": round(held, 1) if share > 0.9 else 0,
                "quiet_for_seconds": round(quiet, 1), "words_heard_last_4_seconds": words4}

    def _pace(self) -> list[dict]:
        """How long earlier slides of the element on screen took: the hymn's pace."""
        run = self.slides[self.pos[self.cur]].run_id
        return [{"slide": i, "seconds": round(d, 1), "words": self._slide(i)["words"]}
                for i, d in self.dwell.items() if self.slides[self.pos[i]].run_id == run]

    def state(self, t: float) -> dict:
        heard = [w for at, w in self.heard if at >= self.since]
        return {
            "on_screen": self._slide(self.cur),
            "next": self._slide(self._after(self.cur)),
            "after_next": self._slide(self._after(self.cur, 2)),
            "seconds_on_screen": round(t - self.since, 1),
            "heard_since_it_went_up": " ".join(heard[-80:]),
            "just_heard": " ".join(w for at, w in self.heard if at > t - 5),
            "sound": self._sound(t),
            "earlier_slides_of_this_element": self._pace(),
        }

    # --- during the service -------------------------------------------------
    def step(self, t, words, levels):
        self.heard += [(w.at, w.text) for w in words]
        self.levels += [(l.at, l.db) for l in levels]
        self.news = self.news or bool(words)
        if t < self.busy_until or self._held(t):
            return []
        gap = t - self.last_ask
        if not (gap >= MAX_GAP or (self.news and gap >= MIN_GAP)):
            return []
        nxt = self._after(self.cur)
        if nxt is None:
            return []
        state = self.state(t)
        try:
            res, latency = self.client.ask(state, {"move": {"type": "choice", "instructions": INSTRUCTIONS,
                                                            "criteria": CRITERIA}})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"TypeSafe refused the key ({e.code})")
            self.stats_["errors"] += 1
            self.last_ask = t
            return []
        except (urllib.error.URLError, TimeoutError, OSError):
            self.stats_["errors"] += 1             # live: keep the slide up and ask again
            self.last_ask = t
            return []
        st = self.stats_
        st["calls"] += 1
        st["input_tokens"] += res["usage"]["input_tokens"]
        st["latency"].append(latency)
        st["model"] = res.get("model")
        if st["calls"] % 200 == 0:
            print(f"  jev: {st['calls']} calls by {t / 60:.1f} min", file=sys.stderr)
        self.last_ask, self.news = t, False
        self.busy_until = t + latency
        p = res["answers"]["move"]["probabilities"]
        go = p.get("next", 0) + p.get("skip", 0)
        cover = self.slides[self.pos[self.cur]].is_cover
        if go < (LEAVE_COVER_AT if cover else ADVANCE_AT):
            return []
        to = self._after(self.cur, 2) if p.get("skip", 0) > p.get("next", 0) else nxt
        if to is None:
            return []
        at = t + latency                            # it acts when the answer arrives
        self.dwell[self.cur] = at - self.since
        self.cur, self.since = to, at
        self.moves.append(at)
        return [Decision(at, to, f"Jev: next {p.get('next', 0):.2f}, skip {p.get('skip', 0):.2f}",
                         state["just_heard"])]

    def _held(self, t: float) -> bool:
        """SLIDE_OPERATOR.md §6 guards: dwell, cooldown, rate."""
        cover = self.slides[self.pos[self.cur]].is_cover
        if t - self.since < (GUARDS["MIN_DWELL_HOLD"] if cover else GUARDS["MIN_DWELL"]):
            return True
        if self.moves and t - self.moves[-1] < GUARDS["COOLDOWN"]:
            return True
        return sum(1 for m in self.moves if m > t - 60) >= GUARDS["MAX_RATE"]

    def stats(self) -> dict:
        st, lat = self.stats_, sorted(self.stats_["latency"])
        return {"model": st["model"], "calls": st["calls"], "errors": st["errors"],
                "input_tokens": st["input_tokens"],
                "cost_usd": round(st["input_tokens"] * PRICE_PER_MTOK / 1e6, 4),
                "latency_median_s": round(lat[len(lat) // 2], 3) if lat else None,
                "latency_p90_s": round(lat[int(len(lat) * 0.9)], 3) if lat else None}
