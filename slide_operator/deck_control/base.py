"""The adapter contract from SLIDE_OPERATOR.md §13.

Reading the slide back is not optional. §8's whole treatment of manual
intervention rests on noticing that the displayed slide changed without us
asking — there is no other signal that a person took over.
"""
from __future__ import annotations

from typing import Protocol


class Deck(Protocol):
    def current_slide(self) -> int | None:
        """1-based index actually on screen, or None if nothing is presenting."""

    def goto(self, index: int) -> bool:
        """Show this slide. True if the deck confirms it took effect."""

    def total(self) -> int:
        """Slides in the presentation, 0 if unknown."""
