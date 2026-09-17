"""Reference slide timeline for a recorded service (TESTING.md, "Ground truth").

The livestream never shows the slides, so the reference is built from the audio.
It is non-causal: it sees the whole transcript, which the live engine never does.
Where the transcript cannot say which slide belonged on screen, the reference
allows a set of slides instead of guessing one.
"""
from __future__ import annotations

import bisect
import json
import sys
from pathlib import Path

from rapidfuzz import fuzz

from ..audio import music as music_mod
from ..ingest import deck as deck_mod, melody
from ..ingest.text import content_words
from ..prepare.service_map import Candidate, _is_credit, _monotonic_chain

MIN_WORDS = 4
ACCEPT = 60.0        # transcripts are noisy, singing far more so; the chain rejects strays
DUPLICATE = 90.0     # two slides this similar are interchangeable on screen
MAX_INTERNAL_GAP = 3.0   # a pause this long means the element had not begun yet
CLUSTER_GAP = 25.0       # music further apart than this is a different element
MIN_SUNG_PER_SLIDE = 4.0 # a stretch too short for the run cannot be its music


def listen_text(s: deck_mod.Slide) -> list[str]:
    """Words a listener could hear while this slide is up."""
    words = [] if _is_credit(s.body) else content_words(s.body)
    return words + content_words(getattr(s, "lyrics", ""))


def _transcript(words: list[dict]):
    parts, starts, owner = [], [], []
    pos = 0
    for i, w in enumerate(words):
        for t in content_words(w["w"]):
            parts.append(t); starts.append(pos); owner.append(i)
            pos += len(t) + 1
    return " ".join(parts), starts, owner


def build(slides: list[deck_mod.Slide], words: list[dict], music: dict | None = None,
          aligned: dict | None = None) -> dict:
    text, starts, owner = _transcript(words)

    def time_at(offset: int, key: str) -> float:
        k = max(0, bisect.bisect_right(starts, offset) - 1)
        return words[owner[k]][key]

    cands = []
    for s in slides:
        lw = listen_text(s)
        if s.is_cover or len(lw) < MIN_WORDS:
            continue
        m = fuzz.partial_ratio_alignment(" ".join(lw), text)
        if m and m.score >= ACCEPT:
            cands.append(Candidate(s.index, m.score, m.dest_start, m.dest_end, "transcript"))
    chosen = _monotonic_chain(cands, strict=True)
    by_index = {s.index: s for s in slides}

    def span(c: Candidate) -> dict:
        """Trim leading tokens cut off from the rest by a long silence.

        A reading's text can match a stray "Amen" minutes before the reading
        actually starts; anchoring there reports the element far too early.
        """
        lo = max(0, bisect.bisect_right(starts, c.start) - 1)
        hi = max(lo, bisect.bisect_right(starts, max(c.start, c.end - 1)) - 1)
        limit = lo + max(1, (hi - lo) // 4)
        i = lo
        while i < hi and i < limit and (
                words[owner[i + 1]]["start"] - words[owner[i]]["end"] > MAX_INTERNAL_GAP):
            i += 1
        return {"t0": words[owner[i]]["start"], "t1": words[owner[hi]]["end"],
                "score": round(c.score, 1)}

    onsets = {i: span(c) for i, c in sorted(chosen.items())}

    # An element cannot begin while the previous element's music is still
    # playing. A hymn's closing line shares enough wording with what follows to
    # drag the next slide's onset back into the singing.
    if music:
        for i, o in onsets.items():
            if by_index[i].musical:
                continue
            for r in music["regions"]:
                if r["t0"] <= o["t0"] < r["t1"]:
                    o["t0"] = max(o["t0"], r["t1"])
                    o["t1"] = max(o["t1"], o["t0"])

    order = sorted(onsets)
    segments = []
    for a, b in zip(order, order[1:]):
        t0a, t1a, t0b = onsets[a]["t0"], onsets[a]["t1"], onsets[b]["t0"]
        between = list(range(a + 1, b))
        if between and by_index[a + 1].is_cover and t1a < t0b:
            # Eager in: the cover belongs on screen once slide a's content is spent.
            segments.append({"t0": t0a, "t1": t1a, "allowed": [a]})
            segments.append({"t0": t1a, "t1": t0b, "allowed": between})
        else:
            # Slides that never matched may or may not have been shown; allow them all.
            segments.append({"t0": t0a, "t1": t0b, "allowed": [a] + between})
    last = order[-1]
    segments.append({"t0": onsets[last]["t0"], "t1": onsets[last]["t1"], "allowed": [last]})

    if music:
        segments = _merge(segments, _sung_spans(slides, music, onsets, aligned or {}))

    dups = _duplicates(slides)
    for seg in segments:
        seg["allowed"] = sorted({x for a in seg["allowed"] for x in dups.get(a, {a})})
    return {"onsets": onsets, "segments": segments}


def _sung_spans(slides, music: dict, onsets: dict, aligned: dict) -> list[dict]:
    """Bound each sung run by the music heard between its neighbouring anchors.

    Stanza boundaries are NOT asserted. Nothing in the audio establishes them
    well enough to grade against, so the reference says only "some slide of this
    hymn belongs on screen now" and leaves stanza timing to a human ear.
    """
    runs: dict[int, list] = {}
    for s in slides:
        if s.musical:
            runs.setdefault(s.run_id, []).append(s)
    spans = []
    for members in runs.values():
        idx = [s.index for s in members]
        before = [i for i in onsets if i < min(idx)]
        after = [i for i in onsets if i > max(idx)]
        lo = onsets[max(before)]["t1"] if before else 0.0
        hi = onsets[min(after)]["t0"] if after else float("inf")
        regs = [r for r in music["regions"] if r["t1"] > lo and r["t0"] < hi]
        if not regs:
            continue
        # A sung element is sung in ONE stretch of music. Taking the union of every
        # region between two anchors made a six-second acclamation span fourteen
        # minutes, because the next anchored slide sits beyond the sermon.
        clusters: list[list[dict]] = []
        for r in sorted(regs, key=lambda r: r["t0"]):
            if clusters and r["t0"] - clusters[-1][-1]["t1"] <= CLUSTER_GAP:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        # The first cluster long enough — NOT the best-overlapping one. Clusters are
        # a scarce resource shared by consecutive runs, so choosing per-run by
        # overlap handed runs 32, 33 and 35 the same 53:09-57:02 stretch and made
        # the reference assert slides 70 and 76 sung at the same instant. Picking
        # greedily here does strand hymns whose cluster starts before their window
        # (Sept 6 slides 70-81); the real repair is allocating clusters to runs
        # monotonically, in time order, not loosening this choice.
        need = MIN_SUNG_PER_SLIDE * len(idx)
        span_of = lambda c: c[-1]["t1"] - c[0]["t0"]
        regs = next((c for c in clusters if span_of(c) >= need),
                    max(clusters, key=span_of))
        # The element begins when the congregation starts singing, not at the
        # first note: an introduction, or an offering interlude, comes first.
        t0 = max(lo, min(r.get("singing_start", r["t0"]) for r in regs))
        t1 = min(hi, max(r["t1"] for r in regs))
        if t1 - t0 < 10:
            continue

        # Best evidence first: the slide's own printed words, aligned to the audio.
        # This places every slide of a canticle where free transcription places
        # none, and agrees with the tune grid where both are available.
        if all(i in aligned for i in idx) and len(idx) >= 2:
            starts = [aligned[i]["t"] for i in idx]
            if all(b > a for a, b in zip(starts, starts[1:])):
                # A sung element ends when its last word ends, not when the music
                # does — the engine leaves on that clock, so the yardstick must too.
                last_end = aligned[idx[-1]].get("end") or t1
                edges = starts + [last_end]
                for k, slide in enumerate(idx):
                    spans.append({"t0": round(edges[k], 2), "t1": round(edges[k + 1], 2),
                                  "allowed": [slide], "sung": True})
                continue

        # Where the tune's own repeat gives at least one cell per slide, the
        # reference can name the stanza. Where it does not, it stays vague
        # rather than inventing boundaries.
        if len(regs) == 1 and len(idx) >= 2:
            marks = [b for b in regs[0]["boundaries"] if t0 - 0.01 <= b < t1]
            if len(marks) >= len(idx):
                edges = marks[:len(idx)] + [t1]
                for i, slide in enumerate(idx):
                    spans.append({"t0": round(edges[i], 2), "t1": round(edges[i + 1], 2),
                                  "allowed": [slide], "sung": True})
                continue
        spans.append({"t0": round(t0, 2), "t1": round(t1, 2), "allowed": idx, "sung": True})
    return spans


def _merge(base: list[dict], overrides: list[dict]) -> list[dict]:
    """Overrides win where they apply; the rest of each base segment survives."""
    out = []
    for seg in base:
        pieces = [seg]
        for ov in overrides:
            nxt = []
            for p in pieces:
                if ov["t1"] <= p["t0"] or ov["t0"] >= p["t1"]:
                    nxt.append(p)
                    continue
                if p["t0"] < ov["t0"]:
                    nxt.append({**p, "t1": ov["t0"]})
                if ov["t1"] < p["t1"]:
                    nxt.append({**p, "t0": ov["t1"]})
            pieces = nxt
        out.extend(pieces)
    out.extend(overrides)
    return sorted((s for s in out if s["t1"] - s["t0"] > 0.5), key=lambda s: s["t0"])


def _duplicates(slides) -> dict[int, set[int]]:
    """Slides carrying the same text are interchangeable. This service reads the
    Gospel once but the deck shows it twice."""
    content = [s for s in slides if len(listen_text(s)) >= MIN_WORDS]
    groups: dict[int, set[int]] = {}
    for i, a in enumerate(content):
        for b in content[i + 1:]:
            if fuzz.ratio(" ".join(listen_text(a)), " ".join(listen_text(b))) >= DUPLICATE:
                g = groups.get(a.index, {a.index}) | groups.get(b.index, {b.index})
                for x in g:
                    groups[x] = g
    return groups


def _mmss(t: float) -> str:
    return f"{int(t // 60):2d}:{int(t % 60):02d}"


if __name__ == "__main__":
    run = Path(sys.argv[1])
    slides = deck_mod.load(run / "deck.pptx")
    melody.attach(slides, run / "deck.pptx", run / "lyrics.json")
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    # Two passes: the first binds each sung run to its music, which tells the
    # aligner which text belongs where; the second uses the aligned words.
    music = music_mod.analyze(run)
    ref = build(slides, words, music)
    from ..audio import lyrics_align, note_align
    from ..ingest import score as score_mod
    sung = [g for g in ref["segments"] if g.get("sung")]
    aligned = lyrics_align.align(run, slides, sung)
    # Notes place the boundary where the slides carry different music; where every
    # stanza prints the same tune, the lyrics pick the stanza (ingest/score.py).
    notes = score_mod.read(run, slides)
    combined = note_align.build(run, slides, sung, aligned, notes)
    ref = build(slides, words, music, {**aligned, **combined})
    (run / "reference.json").write_text(json.dumps(ref, indent=2))
    by_index = {s.index: s for s in slides}
    print(f"matched {len(ref['onsets'])}/{len(slides)} slides to the transcript")
    for s in slides:
        o = ref["onsets"].get(s.index)
        tag = f"{_mmss(o['t0'])}-{_mmss(o['t1'])} {o['score']:5.1f}" if o else "      --        "
        print(f"{s.index:3} {'*' if s.is_cover else ' '} {tag}  {s.title[:40]}")
    scored = sum(g["t1"] - g["t0"] for g in ref["segments"])
    exact = sum(g["t1"] - g["t0"] for g in ref["segments"] if len(g["allowed"]) == 1)
    print(f"\nreference covers {scored/60:.1f} min; {exact/scored:.0%} of it pins exactly one slide")
