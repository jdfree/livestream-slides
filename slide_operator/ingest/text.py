"""Text normalization shared by folder and deck ingestion.

Normalization has to be aggressive enough that the same words typed into a
worship folder and onto a slide land on the same string, without being so
aggressive that distinct passages collapse together.
"""
import re
import unicodedata

_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")
# Verse numbers are glued to the following word in both documents: "18Indeed".
_VERSE_GLUE = re.compile(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = text.lower()
    text = _VERSE_GLUE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_words(text: str) -> list[str]:
    """Normalized tokens with pure digits dropped (verse/hymn numbers)."""
    return [t for t in normalize(text).split() if not t.isdigit()]


# Copyright credits and licence lines are typographic metadata, not service
# content. Filtering them is not the liturgical-vocabulary assumption 2.2
# forbids — every folder using licensed music carries these lines, and a "Tune:"
# credit is also the most portable signal that an element is sung.
CREDIT_MARKERS = ("text:", "tune:", "setting:", "\u00a9", "used by permission",
                  "public domain", "onelicense", "ccli")
TUNE_MARKERS = ("tune:", "setting:")


def is_credit(raw: str) -> bool:
    head = (raw or "").lower()[:80]
    return any(m in head for m in CREDIT_MARKERS)


def names_a_tune(raw: str) -> bool:
    return any(m in (raw or "").lower()[:200] for m in TUNE_MARKERS)


def syllables(text: str) -> int:
    """Rough vowel-group count. Cadence only needs relative stanza lengths."""
    total = 0
    for word in normalize(text).split():
        groups = 0
        prev_vowel = False
        for ch in word:
            vowel = ch in "aeiouy"
            if vowel and not prev_vowel:
                groups += 1
            prev_vowel = vowel
        total += max(1, groups)
    return total
