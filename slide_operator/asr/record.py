"""Transcribe a service recording once and persist word-level events.

This is a one-pass offline transcription, so its accuracy is better than a live
streaming recognizer would achieve (TESTING.md). Streaming latency is simulated
at replay time; streaming accuracy is not. Treat scores built on it as an upper
bound until a causal pass exists.
"""
import json
import sys
import time
from pathlib import Path

import mlx_whisper

MODEL = "mlx-community/whisper-large-v3-turbo"


def record(run: Path) -> None:
    t0 = time.time()
    result = mlx_whisper.transcribe(
        str(run / "audio.wav"),
        path_or_hf_repo=MODEL,
        word_timestamps=True,
        language="en",
        condition_on_previous_text=False,   # limits runaway hallucination loops
        hallucination_silence_threshold=2.0,
    )
    n = 0
    with open(run / "words.jsonl", "w") as f:
        for seg in result["segments"]:
            for w in seg.get("words", []):
                f.write(json.dumps({
                    "w": w["word"].strip(),
                    "start": round(w["start"], 2),
                    "end": round(w["end"], 2),
                    "p": round(w.get("probability", 0.0), 3),
                }) + "\n")
                n += 1
    print(f"{n} words in {time.time() - t0:.0f}s -> {run / 'words.jsonl'}")


if __name__ == "__main__":
    record(Path(sys.argv[1]))
