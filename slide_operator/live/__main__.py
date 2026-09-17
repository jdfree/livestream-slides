"""Run the live slide operator.

Rehearse against a recording, with a deck that exists only in memory:

    python3 -m slide_operator.live --run runs/2026-09-13 --speed 30 --until 700

Drive PowerPoint for real, from the sound-board feed:

    python3 -m slide_operator.live --run runs/2026-09-13 --deck powerpoint \\
        --audio device --asr live

`--intervene 600:9` scripts a person moving the deck, which is the only way to
exercise §8 — a recording carries no trace of anyone touching the keyboard.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..audio.capture import DeviceCapture, FileCapture
from ..deck_control.powerpoint import PowerPointDeck
from ..deck_control.virtual import VirtualDeck
from .harness import Harness
from .hud import Hud


class ReplayASR:
    """Words from an earlier transcription, released on the service clock.

    Lets the loop be tested at speed without waiting on recognition. The engine
    sees each word no earlier than it was actually spoken, plus the commit
    latency streaming transcription was measured to cost.
    """

    window = 12.0

    def __init__(self, path: Path, latency: float = 3.5):
        self.words = [json.loads(l) for l in open(path)]
        self.i, self.latency, self._last = 0, latency, -1e9

    def due(self, now: float) -> bool:
        return now - self._last >= 0.25

    def feed(self, tail, now: float) -> list[dict]:
        self._last = now
        out = []
        while self.i < len(self.words) and self.words[self.i]["end"] + self.latency <= now:
            out.append(self.words[self.i])
            self.i += 1
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--deck", choices=["virtual", "powerpoint"], default="virtual")
    ap.add_argument("--audio", choices=["file", "device"], default="file")
    ap.add_argument("--device", default=None)
    ap.add_argument("--asr", choices=["replay", "live"], default="replay")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--until", type=float, default=None)
    ap.add_argument("--hud-port", type=int, default=8792)
    ap.add_argument("--intervene", action="append", default=[],
                    help="t:slide — script a human moving the deck")
    a = ap.parse_args()

    capture = (FileCapture(a.run / "audio.wav", speed=a.speed) if a.audio == "file"
               else DeviceCapture(device=a.device))
    if a.asr == "replay":
        asr = ReplayASR(a.run / "words.jsonl")
    else:
        from ..asr.stream import StreamingASR
        asr = StreamingASR()

    hud = Hud(a.run / "review" / "slides", port=a.hud_port)
    url = hud.start()

    if a.deck == "powerpoint":
        deck = PowerPointDeck()
        if not deck.is_presenting():
            print("PowerPoint is not presenting — start the slide show first.")
            return
    else:
        deck = VirtualDeck(total=0)

    h = Harness(a.run, deck, capture, asr=asr, hud=hud)
    if a.deck == "virtual":
        deck._total = len(h.slides)
        for spec in a.intervene:
            when, index = spec.split(":")
            deck.schedule_human(float(when), int(index))
            print(f"scripted: a person moves to slide {index} at {float(when):.0f}s")

    print(f"HUD: {url}   deck: {a.deck}   audio: {a.audio} x{a.speed}   words: {a.asr}")
    capture.start()
    try:
        h.run(until=a.until)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()

    print(f"\n{len(h.state.decisions)} decisions, {len(h.state.interventions)} interventions")
    for d in h.state.decisions:
        print(f"  {int(d['t']//60):2d}:{d['t']%60:04.1f}  {d['from']:3} -> {d['to']:<3} {d['rule']}")
    for iv in h.state.interventions:
        print(f"  {int(iv['t']//60):2d}:{iv['t']%60:04.1f}  HUMAN {iv['event']}: {iv['from']} -> {iv['to']}")
    hud.stop()


if __name__ == "__main__":
    main()
