"""Live audio into a rolling buffer, plus a file source for rehearsal.

The live engine needs the same thing the replay engine gets from a wav file — a
growing stream of samples with honest timestamps — but arriving as the service
happens. Both sources below present that same interface, so the harness does not
care which it is attached to.
"""
from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import numpy as np

RATE = 16000          # everything downstream assumes 16 kHz mono
BUFFER_SECONDS = 900  # fifteen minutes of history is plenty for re-anchoring


class _Rolling:
    def __init__(self, seconds: int = BUFFER_SECONDS):
        self._buf = np.zeros(seconds * RATE, dtype=np.float32)
        self._written = 0
        self._lock = threading.Lock()

    def write(self, block: np.ndarray) -> None:
        with self._lock:
            n = len(block)
            if n >= len(self._buf):
                self._buf[:] = block[-len(self._buf):]
            else:
                self._buf = np.roll(self._buf, -n)
                self._buf[-n:] = block
            self._written += n

    @property
    def seconds(self) -> float:
        return self._written / RATE

    def tail(self, seconds: float) -> np.ndarray:
        with self._lock:
            n = min(int(seconds * RATE), self._written, len(self._buf))
            return self._buf[-n:].copy() if n else np.zeros(0, np.float32)

    def window(self, t0: float, t1: float) -> np.ndarray:
        """Samples between two service-clock times, as far back as the buffer holds."""
        with self._lock:
            end = self._written - int(t0 * RATE)
            start = self._written - int(t1 * RATE)
            lo = max(0, len(self._buf) - end)
            hi = max(lo, len(self._buf) - max(0, start))
            return self._buf[lo:hi].copy()


class DeviceCapture:
    """Sound-board feed through an input device."""

    def __init__(self, device: int | str | None = None, channels: int = 1):
        self.device, self.channels = device, channels
        self.buffer = _Rolling()
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        def cb(indata, frames, time_info, status):
            mono = indata.mean(axis=1) if indata.ndim > 1 else indata
            self.buffer.write(np.ascontiguousarray(mono, dtype=np.float32))

        self._stream = sd.InputStream(samplerate=RATE, channels=self.channels,
                                      device=self.device, dtype="float32",
                                      blocksize=int(RATE * 0.25), callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop(); self._stream.close(); self._stream = None

    @property
    def elapsed(self) -> float:
        return self.buffer.seconds


class FileCapture:
    """A recording played at wall-clock speed, so a rehearsal runs like a service."""

    def __init__(self, path: Path, speed: float = 1.0):
        w = wave.open(str(path))
        if w.getframerate() != RATE:
            raise ValueError(f"{path} is {w.getframerate()} Hz; resample to {RATE} first")
        self._pcm = (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                     .astype(np.float32) / 32768.0)
        self.speed = speed
        self.buffer = _Rolling()
        self._thread = None
        self._stop = threading.Event()

    def start(self) -> None:
        def run():
            block = int(RATE * 0.25)
            for i in range(0, len(self._pcm), block):
                if self._stop.is_set():
                    return
                self.buffer.write(self._pcm[i:i + block])
                time.sleep(0.25 / self.speed)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def elapsed(self) -> float:
        return self.buffer.seconds
