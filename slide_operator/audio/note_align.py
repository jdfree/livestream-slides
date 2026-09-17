"""Match the printed notes to the notes actually sung, and combine with lyrics.

Neither source is used alone (see ingest/score.py):

  * Where a run's slides carry **different** notation — a canticle, a psalm — the
    notes place each boundary, and the match cost says whether this really is
    that music.
  * Where the slides carry the **same** notation — every stanza of a hymn — the
    notes cannot say which stanza, so the lyric alignment picks it and the notes
    only pull the boundary onto a real sung note.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

FFT, HOP = 2048, 512
MIN_NOTE = 0.25          # shorter than this is not a sung note
GATE = 0.50              # cost above this: the audio is not this music
SNAP = 1.5               # how far a lyric onset may be pulled onto a sung note


def _audio_notes(pcm, sr, t0: float, t1: float) -> list[tuple[float, int]]:
    fps = sr / HOP
    win = np.hanning(FFT)
    freqs = np.fft.rfftfreq(FFT, 1 / sr)
    ok = (freqs > 80) & (freqs < 2000)
    midi = np.zeros_like(freqs)
    midi[ok] = 69 + 12 * np.log2(np.maximum(freqs[ok], 1e-9) / 440.0)
    pc = np.zeros(len(freqs), int)
    pc[ok] = np.round(midi[ok]).astype(int) % 12
    masks = [(pc == p) & ok for p in range(12)]

    chroma = []
    for k in range(int(t0 * fps), int(t1 * fps)):
        seg = pcm[k * HOP:k * HOP + FFT]
        if len(seg) < FFT:
            break
        mag = np.abs(np.fft.rfft(seg * win))
        chroma.append([mag[m].sum() for m in masks])
    if not chroma:
        return []
    dom = np.array(chroma).argmax(axis=1)
    out, start = [], 0
    for i in range(1, len(dom) + 1):
        if i == len(dom) or dom[i] != dom[start]:
            if (i - start) / fps >= MIN_NOTE:
                out.append((t0 + start / fps, int(dom[start])))
            start = i
    return out


def _cost(a: int, b: int) -> float:
    d = min((a - b) % 12, (b - a) % 12)
    return 0.0 if d == 0 else (0.5 if d == 1 else 1.0)


def _dtw(score: list[int], audio: list[tuple[float, int]]):
    n, m = len(score), len(audio)
    if not n or not m:
        return 1.0, []
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = _cost(score[i - 1], audio[j - 1][1]) + min(
                D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        step = int(np.argmin([D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]]))
        if step == 0:
            i, j = i - 1, j - 1
        elif step == 1:
            i -= 1
        else:
            j -= 1
    return float(D[n, m] / max(n, m)), path[::-1]


def combine(run: Path, slides, spans: list[dict], aligned: dict, notes: dict) -> dict:
    """Final per-slide onsets for sung runs, from notes and lyrics together."""
    w = wave.open(str(run / "audio.wav"))
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    by = {s.index: s for s in slides}
    out: dict[int, dict] = {}

    # Group by the deck's own runs: the reference emits one segment per sung
    # slide, so a segment's allowed set is a single slide and cannot define a hymn.
    runs: dict[int, list[int]] = {}
    for sl in slides:
        if sl.musical and notes.get(sl.index):
            runs.setdefault(sl.run_id, []).append(sl.index)

    for idx in runs.values():
        if len(idx) < 2:
            continue
        touching = [sp for sp in spans if set(sp["allowed"]) & set(idx)]
        if not touching:
            continue
        span = {"t0": min(sp["t0"] for sp in touching),
                "t1": max(sp["t1"] for sp in touching)}
        seq, owner = [], []
        for i in idx:
            seq += notes[i]
            owner += [i] * len(notes[i])
        audio = _audio_notes(pcm, sr, max(0.0, span["t0"] - 2.0), span["t1"] + 2.0)
        cost, path = _dtw(seq, audio)
        distinct = len({tuple(notes[i]) for i in idx}) > 1

        first: dict[int, float] = {}
        for si, aj in path:
            first.setdefault(owner[si], audio[aj][0])

        for i in idx:
            lyric = aligned.get(i, {}).get("t")
            end = aligned.get(i, {}).get("end")
            last_start = aligned.get(i, {}).get("last_start")
            if distinct and cost <= GATE and i in first:
                # The match window reaches a little before the singing so the first
                # note is not clipped; an onset must still not land in the intro.
                t = max(first[i], span["t0"])
                if lyric is not None:
                    # Two independent measurements of the same instant, each noisy
                    # in its own way: notes ran early on one boundary and late on
                    # two others, lyrics the reverse. Their mean beat either alone.
                    t = max((t + lyric) / 2.0, span["t0"])
                    src = "notes+lyrics"
                else:
                    src = "notes"
                out[i] = {"t": round(t, 2), "end": end, "last_start": last_start,
                          "source": src, "cost": round(cost, 3)}
            elif lyric is not None:
                # Same tune on every slide: the lyrics say which stanza, the notes
                # only pull the boundary onto a note that was actually sung.
                near = min((a for a in audio), key=lambda a: abs(a[0] - lyric), default=None)
                t = near[0] if near and abs(near[0] - lyric) <= SNAP else lyric
                out[i] = {"t": round(t, 2), "end": end, "last_start": last_start,
                          "source": "lyrics+note-snap", "cost": round(cost, 3)}
    return out


def build(run: Path, slides, spans: list[dict], aligned: dict, notes: dict) -> dict:
    cache = run / "note_align.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}
    res = combine(run, slides, spans, aligned, notes)
    cache.write_text(json.dumps({str(k): v for k, v in res.items()}, indent=2))
    return res
