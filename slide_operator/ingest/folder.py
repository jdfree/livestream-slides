"""Worship folder ingestion.

Per SLIDE_OPERATOR.md 2.2 the folder's format is not to be trusted: no
liturgical vocabulary, no layout assumptions. All this layer does is get the
text out in reading order and hand it on. Meaning is derived later, by
correlation with the deck.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

from .text import normalize


@dataclass
class Block:
    index: int          # position in reading order
    text: str           # verbatim
    norm: str           # normalized
    start: int = 0      # char offset into the concatenated normalized stream
    end: int = 0


def _from_docx(path: Path) -> list[str]:
    import docx
    return [p.text for p in docx.Document(str(path)).paragraphs]


def _from_pdf(path: Path) -> list[str]:
    """Column-aware extraction: PyMuPDF blocks carry coordinates, so reading
    order can be reconstructed rather than assumed (3, sanity gate)."""
    import fitz
    out: list[str] = []
    for page in fitz.open(str(path)):
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        mid = page.rect.width / 2
        left = sorted([b for b in blocks if b[0] < mid], key=lambda b: b[1])
        right = sorted([b for b in blocks if b[0] >= mid], key=lambda b: b[1])
        # Single-column pages put nearly everything on one side; two-column
        # pages split. Either way, top-to-bottom then left-to-right is right.
        ordered = left + right if right and left else sorted(blocks, key=lambda b: (b[1], b[0]))
        out.extend(b[4] for b in ordered)
    return out


def load(path: str | Path) -> list[Block]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        raw = _from_docx(path)
    elif suffix == ".pdf":
        raw = _from_pdf(path)
    else:
        raise ValueError(f"unsupported worship folder format: {suffix}")

    blocks: list[Block] = []
    cursor = 0
    for text in raw:
        text = text.strip()
        if not text:
            continue
        norm = normalize(text)
        if not norm:
            continue
        b = Block(index=len(blocks), text=text, norm=norm,
                  start=cursor, end=cursor + len(norm))
        cursor = b.end + 1          # +1 for the joining space
        blocks.append(b)
    return blocks


def stream(blocks: list[Block]) -> str:
    """The whole folder as one normalized string, offsets matching Block.start."""
    return " ".join(b.norm for b in blocks)


def block_at(blocks: list[Block], offset: int) -> Block | None:
    for b in blocks:
        if b.start <= offset <= b.end:
            return b
    return None


def to_json(blocks: list[Block]) -> list[dict]:
    return [asdict(b) for b in blocks]
