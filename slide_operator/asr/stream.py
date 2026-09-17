"""Streaming transcription for the live harness.

Offline transcription sees the whole recording; a live operator cannot. This runs
the recognizer repeatedly over a growing tail and only **commits** words that two
consecutive runs agree on, so a word, once shown to the engine, does not change
underneath it. Committing late is the price of committing safely.
"""
from __future__ import annotations

import time

import numpy as np

MODEL = "mlx-community/whisper-large-v3-turbo"
# Measured on a real service: a 24 s window commits at 5.2 s median and 20.2 s at
# the ninetieth percentile — far too slow for an engine that must act on the last
# word of a slide. A 12 s window halves the median and cuts the tail to 5.9 s. An
# 8 s window is no faster in practice and drops a fifth of the words.
WINDOW = 12.0        # seconds of tail handed to the recognizer
HOP = 2.0            # how often it runs


def _words(result) -> list[dict]:
    out = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            out.append({"w": w["word"].strip(), "start": w["start"], "end": w["end"]})
    return out


class StreamingASR:
    def __init__(self, window: float = WINDOW, hop: float = HOP, model: str = MODEL):
        self.window, self.hop, self.model = window, hop, model
        self._prev: list[dict] = []
        self._committed_until = 0.0     # service-clock time
        self._last_run = -1e9

    def due(self, now: float) -> bool:
        return now - self._last_run >= self.hop

    def feed(self, tail: np.ndarray, now: float) -> list[dict]:
        """Transcribe the tail; return words newly agreed by two runs.

        `tail` ends at `now` on the service clock.
        """
        import mlx_whisper

        self._last_run = now
        if len(tail) < 16000:
            return []
        base = now - len(tail) / 16000.0
        res = mlx_whisper.transcribe(tail, path_or_hf_repo=self.model,
                                     word_timestamps=True, language="en",
                                     condition_on_previous_text=False)
        cur = [{**w, "start": w["start"] + base, "end": w["end"] + base}
               for w in _words(res)]

        # LocalAgreement: a word counts only once two successive runs place the
        # same token at the same moment.
        agreed = []
        for a in cur:
            if a["start"] < self._committed_until:
                continue
            if any(b["w"] == a["w"] and abs(b["start"] - a["start"]) < 0.4
                   for b in self._prev):
                agreed.append(a)
        if agreed:
            self._committed_until = max(a["end"] for a in agreed)
        self._prev = cur
        return agreed
