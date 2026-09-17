"""Who is speaking, and whether they are speaking or singing (SLIDE_OPERATOR.md 2.2).

Roles carry rules that words alone cannot: the liturgist's silence brackets the
offering collection, their words dismiss the children, and a switch to a second
voice for a long unbroken stretch is itself evidence the sermon has begun.

Speaker embeddings separate these two voices cleanly on real service audio —
measured 0.92 and 0.99 similarity within a voice against 0.79 across. No gated
model is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MIN_STRETCH = 4.0      # shorter than this is not enough voice to embed
LEAK_MAX = 12.0        # a short stretch beside the music is singing that leaked out
LEAK_NEAR = 3.0
GAP = 2.0              # silence this long ends a stretch
SAME_VOICE = 0.86      # cosine similarity above this is one speaker


def _stretches(words: list[dict], regions: list[dict]) -> list[tuple[float, float]]:
    """Runs of continuous speech, outside the music."""
    sung = [(r["t0"], r["t1"]) for r in regions]
    out: list[list[float]] = []
    for w in words:
        if any(a <= w["start"] < b for a, b in sung):
            continue
        if out and w["start"] - out[-1][1] <= GAP:
            out[-1][1] = w["end"]
        else:
            out.append([w["start"], w["end"]])
    return [(a, b) for a, b in out if b - a >= MIN_STRETCH]


def analyse(run: Path, regions: list[dict]) -> dict:
    cache = run / "voices.json"
    if cache.exists():
        return json.loads(cache.read_text())

    import wave
    from resemblyzer import VoiceEncoder

    w = wave.open(str(run / "audio.wav"))
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    spans = _stretches(words, regions)

    enc = VoiceEncoder()
    embs = [enc.embed_utterance(pcm[int(a * sr):int(b * sr)]) for a, b in spans]

    # Greedy clustering: a stretch joins the first voice it matches.
    voices: list[list[int]] = []
    centres: list[np.ndarray] = []
    for i, e in enumerate(embs):
        best = max(range(len(centres)), key=lambda k: float(np.dot(centres[k], e)),
                   default=None)
        if best is not None and float(np.dot(centres[best], e)) >= SAME_VOICE:
            voices[best].append(i)
            centres[best] = np.mean([embs[j] for j in voices[best]], axis=0)
        else:
            voices.append([i]); centres.append(e)

    # One voice can be split across several clusters by drift over an hour; merge
    # any whose centres are as close as two samples of the same person.
    # Merge on cluster centres, not on any matching pair: two different leaders on
    # one microphone reached 0.90 in places, so single-linkage chains them into one
    # person and the whole service collapses to a single voice.
    merged = True
    while merged and len(centres) > 1:
        merged = False
        for a in range(len(centres)):
            for b in range(a + 1, len(centres)):
                if float(np.dot(centres[a], centres[b])) >= SAME_VOICE:
                    voices[a] += voices[b]
                    centres[a] = np.mean([embs[j] for j in voices[a]], axis=0)
                    del voices[b], centres[b]
                    merged = True
                    break
            if merged:
                break

    total = [sum(spans[i][1] - spans[i][0] for i in v) for v in voices]
    longest = [max((spans[i][1] - spans[i][0] for i in v), default=0) for v in voices]
    # Not whoever speaks most — the sermon makes the preacher the biggest talker
    # by far (measured 1217 s against 180 s). The liturgist is whoever opens the
    # service and then keeps reappearing across its elements.
    # A cluster of short stretches hugging the music is congregation singing that
    # leaked past a region edge, not a person.
    def leaked(k: int) -> bool:
        return all(
            spans[i][1] - spans[i][0] <= LEAK_MAX
            and any(r["t0"] - LEAK_NEAR <= spans[i][0] <= r["t1"] + LEAK_NEAR
                    for r in regions)
            for i in voices[k])

    leaders = [k for k in range(len(voices)) if not leaked(k)]
    # A service has more than one leader: this one has a liturgist, a second
    # reader who also leads the prayers, and a preacher. The preacher is the
    # leader who holds the floor for one long unbroken stretch; the liturgist is
    # whoever opens the service. The rest are leaders too, and for the rules that
    # care (9) what matters is that *a leader* is speaking.
    first_at = {k: min(spans[i][0] for i in voices[k]) for k in leaders}
    preacher = max(leaders, key=lambda k: longest[k]) if leaders else None
    rest = [k for k in leaders if k != preacher]
    liturgist = min(rest, key=lambda k: first_at[k]) if rest else None

    def role_of(k: int) -> str:
        if k == preacher:
            return "PREACHER"
        if k == liturgist:
            return "LITURGIST"
        return "CONGREGATION" if leaked(k) else "LEADER"

    segs = []
    for k, v in enumerate(voices):
        role = role_of(k)
        mode = "SUNG" if role == "CONGREGATION" else "SPOKEN"
        for i in v:
            segs.append({"t0": round(spans[i][0], 2), "t1": round(spans[i][1], 2),
                         "role": role, "voice": k, "mode": mode})
    for r in regions:
        # Only the sung part of a music region is the congregation. A region can
        # open with a minute of ambient noise and a leader still speaking over it;
        # labelling all of it SUNG made a preacher's prayer read as singing.
        start = r.get("singing_start", r["t0"])
        if r["t1"] - start >= 3.0:
            segs.append({"t0": start, "t1": r["t1"], "role": "CONGREGATION",
                         "voice": -1, "mode": "SUNG"})
    segs.sort(key=lambda s: s["t0"])

    out = {"segments": segs,
           "voices": [{"voice": k, "role": role_of(k),
                       "speech_s": round(total[k], 1),
                       "longest_s": round(longest[k], 1)} for k in range(len(voices))]}
    cache.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    import sys
    from . import music as music_mod
    r = Path(sys.argv[1])
    res = analyse(r, music_mod.analyze(r)["regions"])
    mm = lambda t: f"{int(t//60):2d}:{int(t%60):02d}"
    print("voices found:")
    for v in res["voices"]:
        print(f"  voice {v['voice']}  {v['role']:11} speech {v['speech_s']:6.0f}s"
              f"  longest stretch {v['longest_s']:5.0f}s")
    print("\ntimeline (stretches over 20s):")
    for s in res["segments"]:
        if s["t1"] - s["t0"] >= 20:
            print(f"  {mm(s['t0'])}-{mm(s['t1'])}  {s['role']:13} {s['mode']}")
