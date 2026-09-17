"""Derive the service map by correlating the worship folder with the deck.

Uses no liturgical vocabulary (SLIDE_OPERATOR.md 2.2). The only structural
assumption is that folder and deck describe the same service and share text
where they overlap.

Neither document contains the other. The folder carries elements that are never
displayed (the sermon); the deck carries content the folder omits (hymn lyrics
sung from the screen). So a slide failing to anchor proves nothing by itself —
whether a slide is a cover is decided by its own word count, not by the gap.

Anchoring and cover-ness are orthogonal: "Distribution" is both a cover slide
and printed in the folder.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field

from rapidfuzz import fuzz

from ..ingest import folder as folder_mod
from ..ingest.deck import Slide
from ..ingest.text import content_words, is_credit as _is_credit, names_a_tune

BODY_MIN_WORDS = 8      # below this a body match is not distinctive enough
BODY_ACCEPT = 85.0
TITLE_MIN_CHARS = 6
TITLE_ACCEPT = 88.0
HEADING_MAX_CHARS = 80   # longer than this is body text, not a title line
SHORT_TITLE_CHARS = 12   # short titles collide easily, so demand near-exactness
SHORT_TITLE_ACCEPT = 95.0
# A body match spans real content; a title match spans a heading. Both place the
# slide, but the body match tells us far more about which folder text is on
# screen, so it wins ties and near-ties.
BODY_BONUS = 12.0


@dataclass
class Candidate:
    slide: int
    score: float
    start: int
    end: int
    via: str


@dataclass
class SlideBinding:
    index: int
    title: str
    anchored: bool = False
    is_cover: bool = False
    score: float = 0.0
    via: str = ""
    folder_start: int = -1
    folder_end: int = -1
    folder_block: int = -1
    element: str = ""
    released_by: str = ""
    confidence: str = "LOW"


@dataclass
class ServiceMap:
    slides: list[SlideBinding] = field(default_factory=list)
    unslided: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _candidates(slides: list[Slide], stream: str) -> list[Candidate]:
    """Every plausible placement. The chain decides which survive, so a body
    match rejected for going backwards can still fall back to its title."""
    out: list[Candidate] = []
    for s in slides:
        if s.n_words >= BODY_MIN_WORDS and s.norm:
            m = fuzz.partial_ratio_alignment(s.norm, stream)
            if m and m.score >= BODY_ACCEPT:
                out.append(Candidate(s.index, m.score, m.dest_start, m.dest_end, "body"))
        # Hymn numbers sit on opposite ends in the two documents ("562 Jesus
        # Paid It All" vs "Jesus Paid It All CW 562"), so match on words only.
        title = " ".join(content_words(s.title))
        if len(title) >= TITLE_MIN_CHARS:
            accept = (SHORT_TITLE_ACCEPT
                      if len(title) < SHORT_TITLE_CHARS else TITLE_ACCEPT)
            m = fuzz.partial_ratio_alignment(title, stream)
            if m and m.score >= accept:
                out.append(Candidate(s.index, m.score, m.dest_start, m.dest_end, "title"))
    return out


def _weight(c: "Candidate") -> float:
    return c.score + (BODY_BONUS if c.via == "body" else 0.0)


def _monotonic_chain(cands: list[Candidate], strict: bool = False) -> dict[int, Candidate]:
    """Weighted longest non-decreasing subsequence over folder position.

    Slides advance through the deck, so the folder must advance with them. A
    match that would force the folder backwards is spurious. `strict` forbids two
    slides sharing a position — right for audio, where a moment belongs to one
    slide, wrong for the folder, where one hymn title places every stanza. At most one
    candidate per slide survives, because the chain is built in slide order and
    each step requires a strictly greater slide index.
    """
    if not cands:
        return {}
    cands = sorted(cands, key=lambda c: (c.slide, c.start))
    n = len(cands)
    best = [_weight(c) for c in cands]
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            ahead = (cands[j].start < cands[i].start if strict
                     else cands[j].start <= cands[i].start)
            if cands[j].slide < cands[i].slide and ahead:
                if best[j] + _weight(cands[i]) > best[i]:
                    best[i] = best[j] + _weight(cands[i])
                    prev[i] = j
    end = max(range(n), key=lambda i: best[i])
    chosen: dict[int, Candidate] = {}
    while end != -1:
        chosen[cands[end].slide] = cands[end]
        end = prev[end]
    return chosen


def _block_by_overlap(blocks: list[folder_mod.Block], start: int, end: int):
    """The folder block sharing the most characters with the matched span.

    Attributing by start offset alone mislabels a span that begins a few
    characters inside the preceding block — which happens constantly, since
    hymn titles sit directly after the previous element's credits.
    """
    best, best_ov = None, 0
    for b in blocks:
        ov = min(b.end, end) - max(b.start, start)
        if ov > best_ov:
            best, best_ov = b, ov
    return best


def build(slides: list[Slide], blocks: list[folder_mod.Block]) -> ServiceMap:
    stream = folder_mod.stream(blocks)
    chosen = _monotonic_chain(_candidates(slides, stream))

    bindings: list[SlideBinding] = []
    for s in slides:
        b = SlideBinding(index=s.index,
                         title=(s.title or s.body[:40]).strip(),
                         is_cover=s.is_cover)
        c = chosen.get(s.index)
        if c:
            blk = _block_by_overlap(blocks, c.start, c.end)
            b.anchored = True
            b.score, b.via = round(c.score, 1), c.via
            b.folder_start, b.folder_end = c.start, c.end
            b.folder_block = blk.index if blk else -1
            b.confidence = "HIGH" if (c.via == "body" and c.score >= 95) else "MED"
        bindings.append(b)

    _mark_musical_from_folder(bindings, slides, blocks)
    _label_elements(bindings, blocks)
    _set_released_by(bindings, slides)
    deck_stream = " ".join(" ".join(content_words(s.body)) for s in slides)
    unslided = _find_unslided(bindings, blocks, deck_stream)

    anchored = sum(1 for b in bindings if b.anchored)
    return ServiceMap(
        slides=bindings,
        unslided=unslided,
        stats={
            "slides": len(slides),
            "anchored": anchored,
            "coverage": round(anchored / len(slides), 3) if slides else 0.0,
            "covers": sum(1 for b in bindings if b.is_cover),
            "unanchored_content": sum(
                1 for b in bindings if not b.anchored and not b.is_cover),
            "high_confidence": sum(1 for b in bindings if b.confidence == "HIGH"),
            "folder_blocks": len(blocks),
            "unslided_elements": len(unslided),
        },
    )


def _mark_musical_from_folder(bindings, slides, blocks) -> None:
    """A hymn printed as title-plus-credit is sung even when the deck shows only
    text. The signal is a "Tune:" credit attached to the run's own title — not
    merely near it, since folder blocks routinely run one element's credits into
    the next element's heading.
    """
    by_index = {s.index: s for s in slides}
    by_run: dict[int, bool] = {}
    for b in bindings:
        if b.folder_block < 0:
            continue
        anchor = blocks[b.folder_block]
        if len(anchor.text.strip()) > HEADING_MAX_CHARS:
            continue    # body text that happens to sit beside a credit is not sung
        nxt = blocks[b.folder_block + 1:b.folder_block + 2]
        if any(names_a_tune(x.text) for x in [anchor, *nxt]):
            by_run[by_index[b.index].run_id] = True
    for s in slides:
        if by_run.get(s.run_id):
            s.musical = True


def _label_elements(bindings: list[SlideBinding], blocks: list[folder_mod.Block]) -> None:
    """Carry a human-readable name through. Display only — never logic (3)."""
    for b in bindings:
        if b.folder_block >= 0:
            b.element = blocks[b.folder_block].text.split("\t")[0].strip()[:60]
    last = ""
    for b in bindings:
        if b.element:
            last = b.element
        else:
            b.element = last


def _set_released_by(bindings: list[SlideBinding], slides: list[Slide]) -> None:
    """For every cover slide, the opening words of the next slide with content
    (3: the only thing that releases a cover)."""
    by_index = {s.index: s for s in slides}
    for i, b in enumerate(bindings):
        if not b.is_cover:
            continue
        for nxt in bindings[i + 1:]:
            s = by_index[nxt.index]
            if nxt.is_cover:
                continue
            if s.n_words >= 4 and not _is_credit(s.body):
                b.released_by = " ".join(content_words(s.body)[:12])
                break
            if s.melody_lines:
                # Lyrics are pictures, so the title is the best text available.
                b.released_by = " ".join(content_words(s.title))
                break


# Copyright credits and licence lines are typographic metadata, not service
# content. Filtering them is not the liturgical-vocabulary assumption 2.2
# forbids — every folder that uses licensed music carries these lines.
def _find_unslided(bindings: list[SlideBinding], blocks: list[folder_mod.Block],
                   deck_stream: str) -> list[dict]:
    """Folder text that appears on no slide.

    Asked directly — does this block's wording show up anywhere in the deck? —
    rather than inferred from gaps in the alignment. A slide anchored by its
    title has a very short span, so span-based coverage would wrongly report its
    own body text as never displayed.
    """
    out: list[dict] = []
    cover_at = {b.folder_block: b.index for b in bindings if b.is_cover and b.anchored}
    for blk in blocks:
        if len(blk.norm) < 12:
            continue
        if _is_credit(blk.text):
            continue
        probe = " ".join(content_words(blk.text))
        if not probe or fuzz.partial_ratio(probe, deck_stream) >= 82:
            continue
        after = [b for b in bindings if b.anchored and b.folder_block <= blk.index]
        out.append({
            "block": blk.index,
            "text": blk.text.replace("\n", " ")[:80],
            "slide_displayed": after[-1].index if after else None,
            "at_cover": blk.index in cover_at,
        })
    return out


def to_json(sm: ServiceMap) -> str:
    return json.dumps(asdict(sm), indent=2)
