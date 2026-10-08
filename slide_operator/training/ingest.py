"""Make a training bundle from a new service.

    python -m slide_operator.training.ingest --youtube URL --slides PATH_OR_URL \
        --bulletin PATH_OR_URL [--date YYYY-MM-DD] [--location "St Peter, Fort Collins"]

Also run from the intake page (http://localhost:8791/intake/).

A service is keyed by its date and location: runs/2026-09-20-st-peter-fort-collins/.
The bundle there is the recording (audio.webm), the deck (deck.pptx), the bulletin
(folder.pdf or folder.docx), a manifest (bundle.json), the person's marks.json, and
the transcript, OCR'd lyrics and recognised notes — kept because none can be
rebuilt identically. Everything else written there — music map, alignment, the
engine's decisions, the harness page — is derived.

Uploading a service that already exists replaces its media and everything derived
from them, and carries the person's marks and feedback across byte for byte. The
new bundle is built beside the old one and swapped in only once it is complete, so
a failed upload leaves the existing service as it was.

Paths are read on this machine, so ~/Downloads/... works. A link must download
the file itself: a share link that opens a web page is refused rather than saved
as a broken deck.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs"
DEFAULT_LOCATION = "St Peter, Fort Collins"
KEY = r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*"
KEPT = ("marks.json", "feedback.json")     # the person's work, never regenerated
# Held by the server while it writes marks or feedback, and here while a rebuilt
# bundle is swapped in, so a save cannot land in the copy being thrown away.
WRITE_LOCK = threading.Lock()

STEPS = [
    ("fetch", "Fetch the slides and bulletin"),
    ("audio", "Download the recording"),
    ("convert", "Convert the audio"),
    ("transcribe", "Transcribe"),
    ("prepare", "Correlate bulletin and slides"),
    ("analyse", "Music map, sheet-music OCR and OMR, alignment"),
    ("operator", "Replay the engine"),
    ("harness", "Build the marking harness"),
]


def _env() -> dict:
    """launchd hands its jobs a bare PATH; the tools live elsewhere."""
    extra = [str(Path(sys.executable).parent), "/opt/homebrew/bin", "/usr/local/bin",
             str(Path.home() / ".pyenv/shims")]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "/usr/bin:/bin")])
    return env


def video_id(url: str) -> str:
    """Accept watch, live, youtu.be, shorts and studio.youtube.com links."""
    m = re.search(r"(?:v=|/video/|/live/|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError(f"not a YouTube video link: {url}")
    return m.group(1)


def metadata(url: str) -> dict:
    out = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--no-warnings",
                          f"https://www.youtube.com/watch?v={video_id(url)}"],
                         capture_output=True, text=True, env=_env(), timeout=120)
    if out.returncode:
        raise RuntimeError(f"YouTube refused the link: {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout)


def service_date(meta: dict) -> str:
    raw = meta.get("release_date") or meta.get("upload_date")
    if not raw:
        raise RuntimeError("the video carries no date; give one explicitly")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def service_key(date: str, location: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"date must be YYYY-MM-DD, not {date!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")
    if not slug:
        raise ValueError("a location is needed, e.g. St Peter, Fort Collins")
    return f"{date}-{slug}"


def _fetch(src: str, run: Path, stem: str, allowed: tuple[str, ...]) -> Path:
    """Copy a local file or download a link into run/<stem>.<ext>, checking that it
    really is one of the allowed kinds."""
    src = src.strip().strip('"').strip("'")
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    else:
        p = Path(src).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"no such file: {p}")
        data = p.read_bytes()
    if data[:4] == b"%PDF":
        ext = ".pdf"
    elif data[:2] == b"PK":
        ext = ".pptx" if b"ppt/" in data[:200_000] else ".docx" if b"word/" in data[:200_000] else ".zip"
    elif data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(f"{src} is a web page, not a file — use a direct-download link or a local path")
    else:
        ext = "?"
    if ext not in allowed:
        raise ValueError(f"{src} is not a {' or '.join(allowed)} file")
    dest = run / f"{stem}{ext}"
    dest.write_bytes(data)
    return dest


def _run(cmd: list[str], log, cwd: Path = REPO) -> None:
    log("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=_env(), text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:
        log(line.rstrip())
    if p.wait():
        raise RuntimeError(f"{Path(str(cmd[0])).name} {' '.join(map(str, cmd[1:3]))} failed (exit {p.returncode})")


def _install(work: Path, dest: Path, log) -> None:
    """Put a freshly built bundle where the service lives, replacing any earlier
    upload and carrying the person's files across as bytes, not re-serialised."""
    with WRITE_LOCK:
        for name in KEPT:
            if (dest / name).exists():
                shutil.copyfile(dest / name, work / name)
                log(f"kept {name} from the earlier upload, unchanged")
        if not (work / "marks.json").exists():
            (work / "marks.json").write_text("[]\n")
        if dest.exists():
            old = dest.with_name(f".{dest.name}.old")
            shutil.rmtree(old, ignore_errors=True)
            dest.rename(old)
            try:
                work.rename(dest)
            except BaseException:
                old.rename(dest)
                raise
            shutil.rmtree(old, ignore_errors=True)
        else:
            work.rename(dest)


def build(youtube: str, slides: str, bulletin: str, date: str | None = None,
          location: str = DEFAULT_LOCATION, log=print, step=lambda name: None) -> Path:
    py = sys.executable
    step("fetch")
    meta = metadata(youtube)
    date = date or service_date(meta)
    key = service_key(date, location)
    dest = RUNS / key
    run = RUNS / f".{key}.new"              # built here, swapped in when complete
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    logfile = open(run / "ingest.log", "a")
    def log2(line):
        log(line); logfile.write(line + "\n"); logfile.flush()
    log2(f"{meta.get('title')}  ({date}, {location}, {int(meta.get('duration') or 0) // 60} min)")
    try:
        if dest.exists():
            log2(f"runs/{key} exists: its media will be replaced and its marks kept")
        deck = _fetch(slides, run, "deck", (".pptx",))
        folder = _fetch(bulletin, run, "folder", (".pdf", ".docx"))
        log2(f"slides -> {deck.name}, bulletin -> {folder.name}")

        step("audio")
        _run([py, "-m", "yt_dlp", "-f", "bestaudio", "--no-warnings", "--no-progress",
              "-o", str(run / "audio.original.%(ext)s"),
              f"https://www.youtube.com/watch?v={video_id(youtube)}"], log2)
        original = next(run.glob("audio.original.*"))

        step("convert")
        ffmpeg = shutil.which("ffmpeg", path=_env()["PATH"]) or "ffmpeg"
        # 16 kHz mono for the recogniser and the music map; 32 kbps mono Opus is the
        # bundle's copy — small enough to commit, and what the harness plays.
        _run([ffmpeg, "-y", "-v", "error", "-i", original, "-ac", "1", "-ar", "16000", run / "audio.wav"], log2)
        _run([ffmpeg, "-y", "-v", "error", "-i", original, "-vn", "-ac", "1", "-c:a", "libopus",
              "-b:a", "32k", "-application", "audio", run / "audio.webm"], log2)

        step("transcribe")
        _run([py, "-m", "slide_operator.asr.record", run], log2)
        step("prepare")
        _run([py, "-m", "slide_operator", "prepare", run], log2)
        step("analyse")
        _run([py, "-m", "slide_operator.replay.oracle", run], log2)
        step("operator")
        _run([py, "-m", "slide_operator.training.runner", run], log2)
        step("harness")
        _run([py, "-m", "slide_operator.replay.review", run], log2)

        (run / "bundle.json").write_text(json.dumps({
            "service": key, "date": date, "location": location, "title": meta.get("title"),
            "youtube": f"https://www.youtube.com/watch?v={video_id(youtube)}",
            "slides_source": slides, "bulletin_source": bulletin,
            "created": datetime.now().isoformat(timespec="seconds")}, indent=2) + "\n")
        _install(run, dest, log2)
    except BaseException:
        # A failed upload leaves the existing service exactly as it was.
        logfile.close()
        shutil.rmtree(run, ignore_errors=True)
        raise
    log2(f"done: open /{key}/review/")
    logfile.close()
    return dest


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    t0 = time.time()
    r = build(opt("--youtube"), opt("--slides"), opt("--bulletin"), opt("--date"),
              opt("--location") or DEFAULT_LOCATION)
    print(f"built {r} in {time.time() - t0:.0f}s")
