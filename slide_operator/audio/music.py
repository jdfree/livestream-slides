"""Music-region and stanza-boundary detection (SLIDE_OPERATOR.md 5.1).

During hymns the recognizer emits nothing at all — on this corpus, 11 of 55
minutes carry loud audio and zero words. Words cannot drive those stretches, but
the shape of the audio can: music is loud, sustained and wordless, and stanzas
are separated by a short dip for breath or an instrumental turn.

Deliberately crude: energy only, no model. The point is a signal that exists when
transcription does not.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

FRAME = 0.25
# Calibrate against the service, not the recording. Two services of the same room
# came in 25 dB apart, so any threshold measured from the file's noise floor moves
# with the gain. Speech during the service is the stable reference: singing sits
# above it, pauses below.
# Thresholds are relative to the quiet floor OF THE SERVICE, not of the recording:
# two services in the same room came in 25 dB apart, and the pre-service silence
# sits at a different gain again. Do not anchor on speech — one congregation sang
# 12 dB louder than the amplified voice, another 9 dB quieter.
LOUD_OVER_FLOOR = 12.0    # dB above the service's quiet floor to count as audio
MIN_REGION = 5.0         # a sung Amen or acclamation lasts only a few seconds
BRIDGE = 8.0             # join regions split by a stray recognized word
# A chanted psalm is invisible here and nothing below fixes it. Sept 6's 25A sits
# at -50.5 dB (12.7 over floor) and runs 1.17 words/s — quiet AND word-dense — so
# all 159 s of it is rejected and seven slides get no evidence at all.
# Both obvious repairs fail. Raising SPEECH_WPS admits none of it at ANY value:
# level, not rate, is what rejects it. And 1.5 let 108 s of Sept 13's sermon in,
# because that service's speech sits 25 dB over its own floor, so only the rate
# ceiling holds it out. Lowering this bar to 13 recovers 65 s of the psalm but
# admits a 24.8 s blob mid-sermon on Sept 13 — over COVER_MUSIC_MIN, releasing a
# cover that has to hold for 14 minutes. No single dB-over-floor bar separates
# them: the psalm needs <= 12.7 and that blob sits at 13.5, above it.
# Left at 15 until a discriminator other than level exists.
LEVEL_OVER_FLOOR = 15.0  # a quiet pause between elements is not music
SPEECH_WPS = 1.2         # words per second; speech runs well above, singing below
SPEECH_WIN = 6.0         # window over which to judge word rate
DIP_DEPTH = 3.0          # dB below the region's own level to count as a boundary
DIP_MIN_GAP = 6.0        # stanzas are never shorter than this
EDGE = 3.0               # ignore dips at a region's edges
START_WORDS = 20         # a 30 s window this dense means the service has begun
FFT, HOP = 2048, 1024    # chroma frame for tune periodicity
PERIOD_MIN, PERIOD_MAX = 8.0, 70.0
PERIOD_MIN_REGION = 25.0  # shorter than this cannot show a repeat worth trusting
# A hymn opens with an instrumental introduction, and an offering can carry a
# whole interlude, both far quieter than the congregation singing. Singing starts
# at the first stanza cell within this margin of the region's loudest cell.
SINGING_DB = 3.0


def _envelope(wav: Path):
    w = wave.open(str(wav))
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    per = int(sr * FRAME)
    n = len(pcm) // per
    rms = np.sqrt(np.maximum((pcm[:n * per].reshape(n, per) ** 2).mean(axis=1), 1e-9))
    return 20 * np.log10(rms / 32768), FRAME, pcm, sr


def _chroma_energy(pcm: np.ndarray, sr: int, t0: float, t1: float):
    """Pitch-class energy per frame. A hymn repeats its tune every stanza, so the
    chroma sequence repeats with it — which is how the stanza length is measured
    from the music rather than guessed from the words."""
    win = np.hanning(FFT)
    freqs = np.fft.rfftfreq(FFT, 1 / sr)
    ok = freqs > 55
    midi = np.zeros_like(freqs)
    midi[ok] = 69 + 12 * np.log2(np.maximum(freqs[ok], 1e-9) / 440.0)
    pc = np.zeros(len(freqs), int)
    pc[ok] = np.round(midi[ok]).astype(int) % 12
    masks = [(pc == p) & ok for p in range(12)]

    i0, i1 = int(t0 * sr / HOP), int(t1 * sr / HOP)
    C = np.zeros((max(0, i1 - i0), 12), np.float32)
    E = np.zeros(max(0, i1 - i0), np.float32)
    for k in range(i0, i1):
        seg = pcm[k * HOP:k * HOP + FFT]
        if len(seg) < FFT:
            break
        mag = np.abs(np.fft.rfft(seg * win))
        E[k - i0] = mag.sum()
        for p in range(12):
            C[k - i0, p] = mag[masks[p]].sum()
    return C / np.maximum(np.linalg.norm(C, axis=1, keepdims=True), 1e-9), E


def _stanza_grid(C: np.ndarray, E: np.ndarray, fps: float):
    """Period from chroma self-similarity, phase from where boundaries land."""
    hi = min(int(PERIOD_MAX * fps), len(C) // 2)
    lags = range(int(PERIOD_MIN * fps), hi)
    if hi <= int(PERIOD_MIN * fps) + 1:
        return None, []
    sim, lag = max(((C[:-l] * C[l:]).sum(axis=1).mean(), l) for l in lags)

    # A stanza boundary changes harmony and dips in level; score both.
    change = np.r_[0, np.linalg.norm(np.diff(C, axis=0), axis=1)]
    drop = np.r_[0, -np.diff(np.convolve(E, np.ones(8) / 8, "same"))]
    nov = change / max(change.max(), 1e-9) + np.maximum(drop, 0) / max(drop.max(), 1e-9)
    _, phase = max((nov[np.arange(ph, len(nov), lag)].sum(), ph) for ph in range(lag))
    return lag / fps, [round(float(i / fps), 2) for i in np.arange(phase, len(nov), lag)]


def _service_start(words: list[dict]) -> float:
    """Ignore whatever happens before the service: a prelude is not a hymn, and
    the recognizer invents words over quiet rooms."""
    starts = [w["start"] for w in words]
    for i, t in enumerate(starts):
        j = np.searchsorted(starts, t + 30)
        if j - i >= START_WORDS:
            return float(t)
    return 0.0


def analyze(run: Path) -> dict:
    cache = run / "music.json"
    if cache.exists():
        return json.loads(cache.read_text())

    db, step, pcm, sr = _envelope(run / "audio.wav")
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    n = len(db)

    # Sung passages are not wordless — the recognizer emits a garbled trickle.
    # What separates them from speech is the *rate*: a reading runs 2-3 words a
    # second, singing well under one. Requiring zero words split every hymn that
    # was partially transcribed into useless fragments.
    counts = np.zeros(n)
    for w in words:
        i = int(w["start"] / step)
        if 0 <= i < n:
            counts[i] += 1
    win = max(1, int(SPEECH_WIN / step))
    rate = np.convolve(counts, np.ones(win), mode="same") / SPEECH_WIN

    start = _service_start(words)
    spoken = np.zeros(n, bool)
    for w in words:
        if w["start"] >= start:
            spoken[max(0, int(w["start"] / step)):min(n, int(w["end"] / step) + 1)] = True
    speech = float(np.median(db[spoken])) if spoken.any() else float(np.percentile(db, 60))
    svc = db[int(start / step):]
    floor = float(np.percentile(svc, 3)) if len(svc) else float(np.percentile(db, 3))
    loud = db > floor + LOUD_OVER_FLOOR
    music = loud & (rate < SPEECH_WPS)

    spans: list[list[float]] = []
    for i, on in enumerate(music):
        t = i * step
        if on:
            if spans and t - spans[-1][1] <= BRIDGE:
                spans[-1][1] = t + step
            else:
                spans.append([t, t + step])

    smooth = np.convolve(db, np.ones(3) / 3, mode="same")
    regions = []
    for t0, t1 in spans:
        if t1 - t0 < MIN_REGION or t1 <= start:
            continue
        # A region must not *begin* in near-silence. Ambient noise while a leader
        # is still speaking bridges into the music that follows and drags the
        # region's start a minute early — which then reads as singing.
        lo0, hi0 = int(t0 / step), int(t1 / step)
        seg0 = db[lo0:hi0]
        if len(seg0):
            strong = float(np.percentile(seg0, 75)) - SINGING_DB
            idx = np.nonzero(seg0 >= strong)[0]
            if len(idx):
                first = t0 + float(idx[0]) * step
                if first - t0 > 5.0:          # trim only a substantial quiet lead-in
                    t0 = round(first - 2.0, 2)
                    if t1 - t0 < MIN_REGION:
                        continue
        lo, hi = int(t0 / step), int(t1 / step)
        level = float(np.median(db[lo:hi]))
        if level < floor + LEVEL_OVER_FLOOR:
            continue
        dips, last = [], -1e9
        for i in range(lo + int(EDGE / step), hi - int(EDGE / step)):
            t = i * step
            if smooth[i] < level - DIP_DEPTH and t - last >= DIP_MIN_GAP:
                dips.append(round(t, 2))
                last = t
        region = {"t0": round(t0, 2), "t1": round(t1, 2), "level": round(level, 1),
                  "dips": dips, "period": None, "boundaries": [],
                  "cells": [], "singing_start": round(t0, 2)}
        if t1 - t0 >= PERIOD_MIN_REGION:
            C, E = _chroma_energy(pcm, sr, t0, t1)
            period, marks = _stanza_grid(C, E, sr / HOP)
            if period:
                bounds = [round(t0 + m, 2) for m in marks]
                cells = []
                for a, b in zip(bounds, bounds[1:] + [t1]):
                    seg = db[int(a / step):int(b / step)]
                    cells.append(round(float(np.median(seg)), 1) if len(seg) else -99.0)
                loudest = max(cells)
                sung = next((a for a, lv in zip(bounds, cells) if lv >= loudest - SINGING_DB), t0)
                region.update(period=round(period, 2), boundaries=bounds,
                              cells=cells, singing_start=round(sung, 2))
        # Grid cells are tens of seconds wide, so a cell boundary is too coarse to
        # say when singing begins. Measure it: the first point where the level
        # holds within SINGING_DB of the region's loud level for two seconds.
        seg = db[int(t0 / step):int(t1 / step)]
        if len(seg):
            loud = float(np.percentile(seg, 75))
            hold = max(1, int(2.0 / step))
            above = seg >= loud - SINGING_DB
            for i in range(max(1, len(above) - hold)):
                if above[i:i + hold].all():
                    region["singing_start"] = round(t0 + i * step, 2)
                    break
        regions.append(region)

    out = {"service_start": round(start, 2), "floor": round(floor, 1),
           "speech_level": round(speech, 1), "step": step,
           # the envelope travels with the regions: cadence snaps a predicted
           # stanza boundary to the nearest real dip (5.1)
           "envelope": [round(float(x), 1) for x in smooth],
           "regions": regions}
    cache.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    import sys
    r = analyze(Path(sys.argv[1]))
    print(f"service starts {int(r['service_start']//60)}:{int(r['service_start']%60):02d}, "
          f"speech {r['speech_level']} dB, floor {r['floor']} dB, "
          f"{len(r['regions'])} music regions\n")
    for g in r["regions"]:
        mm = lambda x: f"{int(x//60)}:{int(x%60):02d}"
        b = " ".join(mm(x) for x in g["boundaries"])
        per = f"{g['period']:5.1f}s" if g["period"] else "   -  "
        print(f"  {mm(g['t0'])}-{mm(g['t1'])} {g['t1']-g['t0']:5.0f}s {g['level']:6.1f}dB  "
              f"period {per}  sings at {mm(g['singing_start'])}  {b}")
