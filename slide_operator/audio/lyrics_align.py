"""Forced alignment of known slide text to sung audio.

Free transcription fails on singing: 48 seconds of a canticle yielded two words.
But the words are not unknown — they are printed on the slide. Aligning that
known text to the audio is what a person in the pew does, and it places every
slide of a hymn where free recognition places none.

Caveats, measured rather than assumed:
  * Alignment scores on singing run ~0.03 against ~0.24 for speech, and correct
    text out-scores wrong text only narrowly. The score cannot tell which hymn is
    playing; it is usable only because the service map already says which text
    belongs here.
  * A whole region is aligned at once, which uses audio from after each boundary.
    A live operator would align over a growing buffer instead; the timings here
    are therefore an upper bound on what streaming alignment would achieve.
"""
from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import numpy as np

PRE_ROLL = 1.0      # alignment must not be given audio the words are absent from:
                    # every word has to go somewhere, so a long lead-in drags the
                    # first slide's words back into the introduction
MIN_WORDS = 3


def _audio(path: Path):
    w = wave.open(str(path))
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return pcm, w.getframerate()


def _words(text: str) -> list[str]:
    return [x for x in re.sub(r"[^a-z' ]", " ", (text or "").lower()).split() if x]


def _clip_to_music(t0: float, t1: float, regions: list[dict]):
    """Narrow a window to the music actually inside it.

    A sung element's words cannot end after its music has stopped. Handed a span
    that bridges a sermon, the aligner will dutifully spread a six-second
    acclamation across twelve minutes of preaching — which is exactly what
    stranded the deck for 813 seconds.
    """
    hits = [r for r in regions if r["t1"] > t0 and r["t0"] < t1]
    if not hits:
        return None
    return max(t0, min(r["t0"] for r in hits)), min(t1, max(r["t1"] for r in hits))


def align(run: Path, slides, spans: list[dict]) -> dict:
    """Per-slide onsets for each sung span. Cached: the model is large and slow."""
    cache = run / "align.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}

    import torch
    from torchaudio.pipelines import MMS_FA as bundle

    regions = json.loads((run / "music.json").read_text())["regions"]
    pcm, sr = _audio(run / "audio.wav")
    model, tok, aligner = bundle.get_model(), bundle.get_tokenizer(), bundle.get_aligner()
    by = {s.index: s for s in slides}
    out: dict[int, dict] = {}

    for span in spans:
        idxs = [i for i in span["allowed"] if by[i].musical]
        words, owner = [], []
        for i in idxs:
            ws = _words(by[i].lyrics or by[i].body)
            words += ws
            owner += [i] * len(ws)
        if len(words) < MIN_WORDS:
            continue
        window = _clip_to_music(max(0.0, span["t0"] - PRE_ROLL), span["t1"], regions)
        if window is None:
            continue
        t0, t1 = window
        seg = torch.from_numpy(pcm[int(t0 * sr):int(t1 * sr)]).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = model(seg)
        try:
            token_spans = aligner(emission[0], tok(words))
        except Exception:
            continue
        ratio = seg.shape[1] / emission.shape[1] / sr
        for sp, i in zip(token_spans, owner):
            start = round(t0 + sp[0].start * ratio, 2)
            end = round(t0 + sp[-1].end * ratio, 2)
            score = round(sum(x.score for x in sp) / len(sp), 4)
            if i not in out:
                out[i] = {"t": start, "end": end, "last_start": start, "score": score}
            else:
                # A reader reaches the last word before finishing it. That moment —
                # not the word's end, and not the next slide's first word — is when
                # the next slide is due (§6).
                out[i]["end"] = end
                out[i]["last_start"] = start
    cache.write_text(json.dumps({str(k): v for k, v in out.items()}, indent=2))
    return out


if __name__ == "__main__":
    import sys
    from ..ingest import deck as deck_mod, melody
    r = Path(sys.argv[1])
    sl = deck_mod.load(r / "deck.pptx")
    melody.attach(sl, r / "deck.pptx", r / "lyrics.json")
    ref = json.loads((r / "reference.json").read_text())
    spans = [s for s in ref["segments"] if s.get("sung")]
    res = align(r, sl, spans)
    mm = lambda t: f"{int(t//60):2d}:{t%60:04.1f}"
    for i in sorted(res):
        print(f"  slide {i:3} aligned {mm(res[i]['t'])} -> {mm(res[i]['end'])}   score {res[i]['score']}")
