"""Replay the operating policy against a recorded service and score it.

    python -m slide_operator.replay.run runs/<date> [--latency 1.5]

A deterministic baseline, not the whole policy. Implemented: word evidence, the
dwell/cooldown/rate guards (6), cover eager-in and patient-out, the handoff rule,
skipping ahead, and forward re-anchoring on two independent strong matches (7).
Not yet: structural evidence and the stanza clock (5.1), backward correction,
interventions (8), LLM adjudication. The score says what words alone buy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..audio import music as music_mod
from ..ingest import deck as deck_mod, melody
from ..ingest.text import content_words, syllables
from . import verdicts
from .oracle import MIN_WORDS, _duplicates, listen_text

LATENCY = 1.5            # simulated streaming commit delay (s)
MIN_DWELL = 4.0
MIN_DWELL_COVER = 45.0
COOLDOWN = 2.0
MAX_RATE = 4             # moves per rolling 60 s
RECENT = 8               # newest evidence words considered
HEAD = 14                # opening words of a slide
TAIL = 6                 # closing words of a slide
TIER_B = 5               # in-order matches among RECENT words
TIER_A = 7
CONFIRM_WINDOW = 45.0
LOOKAHEAD = 25           # far enough to re-anchor after a long sermon
MUSIC_SKIP_MAX = 8       # cap on how far a music cue may look for its sung slide
PASSABLE_WORDS = 8       # below this a slide cannot be tracked by words at all
MUSIC_CONFIRM = 3.0      # sustained music before it counts as an event
MUSIC_ONSET_CONFIRM = 1.0  # leaving a speaking slide for a sung one: go at once
COVER_MUSIC_MIN = 15.0     # music must be sustained before it releases a cover
SPSYL_PRIOR = 0.55       # seconds per sung syllable before anything is measured
# Biased late on purpose (1): a stanza shown early strands singers mid-verse,
# while one shown late is barely noticed.
SNAP_LO, SNAP_HI = 1.0, 1.4     # window around a predicted stanza boundary
TICK = 0.5
# A slide cannot be finished before its own text could have been read aloud. The
# creed prints "God the Father Almighty" in its FIRST line and its last, so the
# opening line matched the closing six words and reported a 73-word slide spent
# after 6 s; the reading took 33. Measured speech here runs 2.3 words/s, so this
# is a generous fast bound — short slides clear it inside the dwell anyway.
FAST_WPS = 3.5           # fastest plausible reading rate, words per second
# The deck ends acknowledgments -> blank. Nothing is read from the blank and no
# cue releases it, so it is reached on a short clock instead.
FINAL_COVER_DWELL = 3.0
# The collection is silent: the liturgist stops speaking, the plate goes round, and
# no music starts until the offering hymn a minute later. Quiet this long, on a
# slide already read out, is the only cue the offering slide is due.
SILENCE_ADVANCE = 8.0
# A spoken last word is over as it is said; a sung one is held. "...melt the heart
# of stone" was still being sung 3.7 s after this slide's last word began, so
# leaving on the lyric clock stranded the congregation mid-line. The notes know
# better: DTW against the printed staff puts the next stanza later in six of seven
# cases here. Wait for it — but not forever, in case the OMR read the staff wrong.
STANZA_WAIT = 8.0        # furthest past this slide's own end we will wait for the notes

# English function words carry no evidence about position. Not liturgical vocabulary.
_COMMON = set("the and you your our for with that this his him are was have has will all but "
              "not who from they them their she her its into what when then than there shall".split())


def _ev(words: list[str]) -> list[str]:
    return [w for w in words if len(w) > 2 and w not in _COMMON]


def _lcs(a: list[str], b: list[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


class Engine:
    def __init__(self, slides: list[deck_mod.Slide], music: dict | None = None,
                 aligned: dict | None = None):
        self.aligned = aligned or {}   # slide -> aligned first/last sung word
        self.music = music or {"regions": [], "service_start": 0.0}
        self.regions = self.music["regions"]
        self.syll = {s.index: max(1, syllables(s.lyrics or s.body)) for s in slides}
        self.measured: list[float] = []     # seconds per syllable, observed
        self.spent: set[int] = set()        # slides whose content has been heard out
        self.displayed: set[int] = set()    # slides this service has actually shown
        self.dup = _duplicates(slides)      # slides carrying identical text
        self.clock_from = 0.0               # when the current stanza started
        self.run_region: float | None = None  # music region this hymn is being sung in
        self.by = {s.index: s for s in slides}
        self.words = {s.index: _ev(listen_text(s)) for s in slides}
        self.content = {i for i, w in self.words.items()
                        if len(w) >= MIN_WORDS and not self.by[i].is_cover}
        self.last = max(self.by)
        self.cur = slides[0].index
        self.last_move = -1e9
        self.moves: list[dict] = []
        self.recent: list[str] = []
        self.n = 0
        self.strong: list[tuple[float, int, int]] = []   # (t, word count, slide)
        self.last_word_t: float | None = None   # when anything was last heard said

    def _region(self, t: float):
        return next((r for r in self.regions if r["t0"] <= t < r["t1"]), None)

    def _music_target(self, c: int):
        """Nearest sung slide the music can be evidence for, passing over only
        what cannot be missed: cover slides, and slides already heard out."""
        for j in range(c + 1, min(c + MUSIC_SKIP_MAX, self.last) + 1):
            if self.by[j].musical and self.by[j].run_id != self.by[c].run_id:
                return j
            # Pass over only what cannot be missed: cover slides, slides already
            # heard out, and slides carrying too little text to listen for at all
            # (a sung response, a placeholder) — those can never be tracked by words.
            shown = j in self.displayed
            if ((self.by[j].is_cover and shown) or j in self.spent
                    or (not self.by[j].is_cover
                        and (j not in self.content or len(self.words[j]) < PASSABLE_WORDS))):
                # A near-empty slide — a placeholder, a one-line response — can
                # never be tracked by words, so it must not dam the music cue.
                continue
            return None
        return None

    def _next_content(self, c: int):
        return next((i for i in range(c + 1, self.last + 1) if not self.by[i].is_cover), None)

    def tick(self, t: float) -> None:
        """Time-driven rules. Words cannot carry a hymn (5.1), so music does."""
        if t < self.music["service_start"] or t - self.last_move < COOLDOWN:
            return
        # The deck's last slide is the blank following the acknowledgments. Nothing
        # is read from it and no music releases it, so no rule below can ever reach
        # it: the credits hold for FINAL_COVER_DWELL and then it goes up. This sits
        # ahead of the music branch because by now the service is over and the room
        # is quiet, and that branch returns without acting on a spoken slide.
        end_blank = self.cur + 1
        if (end_blank == self.last and self.by[end_blank].is_cover
                and not self.by[self.cur].is_cover
                and t - self.last_move >= FINAL_COVER_DWELL):
            self._move(t, end_blank, "the acknowledgments have been shown; onto the closing blank")
            return
        reg = self._region(t)
        if reg is None:
            # The music stopped. A sung element is over once its own words have
            # been sung out — a final note is held well past the last syllable,
            # so leaving on the aligned end alone lands several seconds early.
            c = self.cur
            a = self.aligned.get(c)
            # A sung Amen or acclamation has no words to align. Nothing can
            # release it except the music stopping, which has just happened.
            done = (t >= a["end"]) if (a and a.get("end")) else True
            if (self.by[c].musical and done
                    and t - self.last_move >= MIN_DWELL):
                after = c + 1
                # _next_content skips covers, but a cover right after a sung
                # response is exactly where the service goes — the blank slide
                # held through the sermon. Prefer it.
                target = (after if after <= self.last and self.by[after].is_cover
                          else self._next_content(c))
                if target and not self.by[target].musical:
                    self._move(t, target, "the singing stopped and this hymn was sung out")
            # The collection is silent. A slide whose own text has been read out is
            # finished, and the quiet that follows is the only cue that the offering
            # slide is due: no music starts until the offering hymn a minute later,
            # which is why the deck sat on the creed for 93 s. Covers are excluded —
            # the blank held through a sermon must survive a pause — and the dwell
            # test keeps this from firing straight after a sung-out move.
            if (not self.by[c].is_cover and c in self.spent
                    and self.last_word_t is not None
                    and t - self.last_word_t >= SILENCE_ADVANCE
                    and t - self.last_move >= MIN_DWELL):
                quiet = self._next_content(c)
                if quiet and not self.by[quiet].musical and quiet in self.content:
                    self._move(t, quiet, "the reading is finished and the room has gone quiet")
            return
        c = self.cur
        # A cover is on screen deliberately — the blank slide held through a sermon.
        # A five-second blip of noise must not take it down; a speaking slide may
        # still yield to a short sung response, so this guard is for covers only.
        if self.by[c].is_cover and reg["t1"] - reg["t0"] < COVER_MUSIC_MIN:
            return
        # Leaving a speaking slide for a sung one happens at the first notes, not
        # after music has been confirmed for several seconds: the congregation
        # needs the hymn on screen through its introduction.
        onset_dwell = MIN_DWELL_COVER if self.by[c].is_cover else MIN_DWELL
        if (t - reg["t0"] >= MUSIC_ONSET_CONFIRM and t - self.last_move >= onset_dwell
                and (self.by[c].is_cover or c in self.content)):
            target = self._music_target(c)
            if target and self.by[target].musical:
                self._move(t, target, "music began and the next element is sung")
                self.run_region = reg["t0"]
                return
        if t - reg["t0"] < MUSIC_CONFIRM:
            return
        dwell = MIN_DWELL_COVER if self.by[c].is_cover else MIN_DWELL
        if t - self.last_move < dwell:
            return
        nxt = c + 1
        if self.by[c].musical and nxt <= self.last and self.by[nxt].run_id == self.by[c].run_id:
            # The slide's own words, aligned to the audio, beat any estimate of
            # how long a stanza should take.
            # A congregation reading along cannot anticipate the next slide, so it
            # must appear the moment they reach the last word of this one — not
            # when the next slide's first word arrives, which is always too late.
            here = self.aligned.get(c) or {}
            a = self.aligned.get(nxt)
            due = here.get("last_start")
            if due is not None:
                # Once this slide's own words are known, they decide. Falling back
                # to the next slide's onset fires a verse early on a hymn whose
                # alignment starts ahead of the singing.
                # But a spoken last word is over as it is said, while a sung one is
                # held: "...melt the heart of stone" was still being sung 3.7 s after
                # this slide's last word began. Where the notes put the next stanza
                # later, they are the better clock, so take the LATER of the two and
                # never the earlier. Bounded by STANZA_WAIT in case the staff was
                # misread; and where alignment runs backwards — tiny slides whose
                # spans overlap, as the Alleluias do — the next start is earlier and
                # this changes nothing at all.
                nxt_t = (a or {}).get("t")
                by_notes = (nxt_t is not None and nxt_t > due
                            and nxt_t <= (here.get("end") or due) + STANZA_WAIT)
                if by_notes:
                    due = nxt_t
                if t >= due:
                    self._move(t, nxt, "the next stanza's notes begin here" if by_notes
                               else "this slide's last word began")
                return
            if a and t >= a["t"]:
                self._move(t, nxt, "the singing reached this slide's words")
                self.run_region = reg["t0"]
                return
            self._stanza_clock(t, reg)      # no aligned words: fall back to the tune
            return
        if self.by[c].musical:
            # Last slide of a sung element: it is finished when its own last word
            # finishes, not when the music stops. An outro runs seconds longer and
            # leaves the congregation staring at text they have already sung.
            here = self.aligned.get(c) or {}
            if here.get("end") and t >= here["end"]:
                target = self._next_content(c)
                if target and not self.by[target].musical:
                    self._move(t, target, "the last word of this element was sung")
                    return
        singing = t >= reg.get("singing_start", reg["t0"])
        if singing:
            # A sung element starts when the congregation starts singing — not at
            # the first note of an introduction, and not during an interlude.
            target = self._music_target(c)
            if target:
                # One region can carry two unrelated elements: a three-fold Amen
                # and the closing hymn are sung in the same stretch of music. That
                # stretch's singing_start belongs to the Amen, so handing the deck
                # to the next run on it raised the hymn 28 s early, before the Amen
                # had been sung at all. A sung element is not abandoned mid-flight:
                # wait for the next element's own words, or failing those, for this
                # slide's to finish.
                if self.by[c].musical and self.by[target].run_id != self.by[c].run_id:
                    due = (self.aligned.get(target) or {}).get("t")
                    if due is None:
                        due = (self.aligned.get(c) or {}).get("end")
                    if due is not None and t < due:
                        return
                self._move(t, target, "singing started and the next element is sung")
                self.run_region = reg["t0"]
            return
        # Before the singing begins, music still means the spoken element is over
        # and the next slide is due: the offering's interlude belongs to the
        # offering slide, which stays up through it. Once singing has started this
        # must not fire, or the deck walks forward through the hymn.
        target = self._next_content(c)
        if (target and (c not in self.content or c in self.spent)
                and not self.by[target].musical and target in self.content):
            # Only onto a slide that is displayed while music plays and has words
            # to hold it there. A sung slide waits for singing; a slide with
            # nothing to listen for should be passed over, not put up.
            self._move(t, target, "music began and this slide's content was finished")

    def _stanza_clock(self, t: float, reg: dict) -> None:
        """Cadence: sung syllables run at a near-constant rate, so the stanza's
        own length predicts its end even when the words are unintelligible. The
        prediction is snapped to a real dip in the audio when one is there."""
        c = self.cur
        nxt = c + 1
        if nxt > self.last or self.by[nxt].run_id != self.by[c].run_id:
            return
        # A hymn is sung in one stretch of music. Once that stretch ends the hymn
        # is over, so a later region — an interlude, a pause — must not resume it.
        if self.run_region is None:
            self.run_region = reg["t0"]
        elif reg["t0"] != self.run_region:
            return
        spsyl = sorted(self.measured)[len(self.measured) // 2] if self.measured else SPSYL_PRIOR
        predicted = self.syll[c] * spsyl
        # A hymn opens with an instrumental introduction. Counting the first stanza
        # from the music's start rather than from the first sung word put the deck
        # a whole stanza ahead for the rest of the hymn.
        start = max(self.last_move, reg.get("singing_start", reg["t0"]), self.clock_from)
        elapsed = t - start
        if elapsed < predicted * SNAP_LO:
            return
        # The tune repeats every stanza, so its measured period is a real boundary
        # rather than a guess from syllables. Prefer it whenever it lands near the
        # predicted end; otherwise fall back to cadence alone.
        mark = next((b for b in reg["boundaries"] if b > start + 2.0), None)
        if mark is not None and start + predicted * SNAP_LO <= mark <= start + predicted * SNAP_HI:
            if t < mark:
                return
            why = "the tune repeated: this stanza is over"
        elif elapsed >= predicted * SNAP_HI:
            why = "cadence says this stanza is over"
        else:
            return
        rate = (t - start) / self.syll[c]
        if 0.25 <= rate <= 1.2:
            self.measured.append(rate)
        self.clock_from = t
        self._move(t, nxt, why)

    def hear(self, t: float, token: str) -> None:
        # Every spoken token, not only the evidence-bearing ones _ev keeps: silence
        # is the absence of speech, and "the" is speech.
        self.last_word_t = t
        for w in _ev(content_words(token)):
            self.recent = (self.recent + [w])[-RECENT:]
            self.n += 1
            self._decide(t)

    def _move(self, t: float, to: int, rule: str) -> None:
        self.moves.append({"t": round(t, 2), "from": self.cur, "to": to, "rule": rule,
                           "heard": " ".join(self.recent)})
        if self.by[to].run_id != self.by[self.cur].run_id:
            self.run_region = None
        self.displayed.add(to)
        self.cur, self.last_move = to, t
        self.clock_from = t
        self.strong.clear()

    def _decide(self, t: float) -> None:
        c, r = self.cur, self.recent
        since = t - self.last_move
        if since < COOLDOWN or sum(1 for m in self.moves if t - m["t"] < 60) >= MAX_RATE:
            return
        cur_hits = _lcs(r, self.words[c])
        cover = self.by[c].is_cover
        # Heard once, spent for good. A slide read out fourteen minutes ago is
        # still finished now — the four most recent words cannot say so.
        # But never before the text could plausibly have been read aloud: a slide
        # that repeats its closing words in its opening line otherwise reports
        # itself finished one line in, and the handoff fires on the spot.
        if (c in self.content and since >= len(self.words[c]) / FAST_WPS
                and _lcs(r[-4:], self.words[c][-TAIL:]) >= 3):
            # Identical slides are spent together: this deck prints the Gospel
            # twice, and the service reads it once.
            self.spent |= self.dup.get(c, {c})

        # Record strong matches anywhere ahead; two independent ones re-anchor (7).
        anchor = None
        for b in range(c + 1, min(c + LOOKAHEAD, self.last) + 1):
            if b in self.content:
                hits = _lcs(r, self.words[b])
                if hits >= TIER_A and hits > cur_hits:
                    prior = [s for s in self.strong
                             if s[2] in (b - 1, b) and self.n - s[1] >= RECENT
                             and t - s[0] <= CONFIRM_WINDOW]
                    self.strong.append((t, self.n, b))
                    anchor = b if prior else None
                    break

        if since < (MIN_DWELL_COVER if cover else MIN_DWELL):
            return

        if cover:
            rel = next((i for i in range(c + 1, self.last + 1) if not self.by[i].is_cover), None)
            if rel in self.content and _lcs(r, self.words[rel][:HEAD]) >= TIER_B:
                return self._move(t, rel, "cover released: the next element began")
        elif c < self.last:
            nxt = c + 1
            spent = c in self.spent
            if self.by[nxt].is_cover and spent:
                return self._move(t, nxt, "onto cover: this slide's content is finished")
            if nxt in self.content:
                if spent and not self.by[c].musical:
                    # Only for spoken text. Inside a hymn the aligned words and the
                    # tune decide; letting the spoken handoff fire there advanced
                    # hymn verses about thirty seconds early, every verse.
                    #
                    # A slide that has been read out is finished whether or not the
                    # next slide continues the same reading. Requiring a shared
                    # title meant Invocation -> Confession -> Absolution each had to
                    # wait until five words of the NEXT slide had been heard, which
                    # is five seconds of the congregation staring at finished text.
                    same = content_words(self.by[c].title) == content_words(self.by[nxt].title)
                    return self._move(t, nxt, "handoff: the reading continues onto the next slide"
                                      if same else "this slide has been read out")
                h = _lcs(r, self.words[nxt][:HEAD])
                if h >= TIER_B and h > cur_hits and not self.by[c].musical:
                    # Inside a hymn the aligned words decide. Garbled singing that
                    # happens to match the next verse's opening fired a verse early.
                    return self._move(t, nxt, "the next slide's opening was heard")
            for b in (c + 2, c + 3):
                if b in self.content and not self.by[c].musical:
                    # Same guard as the rule above: inside a hymn the aligned words
                    # and the tune decide. Garbled singing that happened to match a
                    # later verse's opening jumped the deck two slides forward and
                    # those two were never shown at all. Genuine recovery, when the
                    # deck really has fallen behind, still comes from the re-anchor
                    # rule below, which needs two independent strong matches.
                    h = _lcs(r, self.words[b][:HEAD])
                    if h >= TIER_A and h > cur_hits:
                        return self._move(t, b, f"skipping ahead: slide {b}'s opening heard clearly")
        if anchor:
            return self._move(t, anchor, f"re-anchor: two independent strong matches for slide {anchor}")


def replay(slides, words, music, latency: float, aligned=None) -> Engine:
    """Word events interleaved with a clock, so music rules can fire in silence."""
    eng = Engine(slides, music, aligned)
    events = sorted((w["end"] + latency, w["w"]) for w in words)
    end = (events[-1][0] if events else 0) + 60
    i, t = 0, 0.0
    while t < end:
        while i < len(events) and events[i][0] <= t:
            eng.hear(*events[i])
            i += 1
        eng.tick(t)
        t += TICK
    return eng


def _mmss(t):
    return f"{int(t // 60):2d}:{int(t % 60):02d}"


def main(run: Path, latency: float, no_music: bool = False) -> None:
    slides = deck_mod.load(run / "deck.pptx")
    melody.attach(slides, run / "deck.pptx", run / "lyrics.json")
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    aligned = {}
    if not no_music:
        # note_align overlays align: notes win where they are trustworthy, lyrics
        # remain for sung slides the notes cannot separate.
        for name in ("align.json", "note_align.json"):
            path = run / name
            if path.exists():
                aligned.update({int(k): v for k, v in json.loads(path.read_text()).items()})
    eng = replay(slides, words, None if no_music else music_mod.analyze(run), latency, aligned)
    (run / "decisions.json").write_text(json.dumps({"moves": eng.moves}, indent=2))

    by = {s.index: s for s in slides}
    print("=== console narration ===")
    for m in eng.moves:
        print(f"{_mmss(m['t'])}  {m['from']:>2} -> {m['to']:<2} {by[m['to']].title[:28]:<28} {m['rule']}")
        print(f"        heard: \"{m['heard']}\"")
    res = verdicts.score(run, eng.moves, slides[0].index)
    print(f"\nagainst the human record: {res['correct']}/{res['checked']}"
          f"   late {res['late']}  early {res['early']}  never shown {res['never']}")
    for r in sorted((r for r in res["rows"] if not r["ok"]), key=lambda r: r["want"]):
        err = "never shown" if r["error"] is None else f"{r['error']:+.1f}s"
        print(f"  MISS {_mmss(r['want'])} -> {r['to']:>2} {err:>12}   {r['note'][:52]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    lat = float(args[args.index("--latency") + 1]) if "--latency" in args else LATENCY
    main(Path(args[0]), lat, "--no-music" in args)
