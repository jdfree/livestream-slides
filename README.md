# Slide operator

An AI that listens to a church service and advances the slide deck — the job a
volunteer does from the back of the room, clicking at the right moment for ninety
minutes.

Its central idea is that a slide operator does not transcribe what is said. They
**follow printed words**, and when a hymn starts they follow **printed music**. So
this reads the deck and the worship folder before the service, then listens for
what it already expects to hear: each slide's own lyrics force-aligned to the
audio, and the notes printed on the slide matched against the tune actually sung.

### → **[See it follow a real service](https://jdfree.github.io/livestream-slides/)**

Pick a service and watch what it did: the timeline of music and voices, the slide
it had on screen at every moment, what it believed that slide said, every
transition with the reason it fired, and the transitions a person marked.

## How it is graded

**By a person, not by itself.** For each service, someone listens to the recording
in the marking harness and presses **Mark** at every moment the deck should change —
"slide 8 → 9, now" — adding notes wherever something deserves a comment. Those
transition marks are the training labels and the only measure, committed with the
service in [`runs/<date>/marks.json`](runs/2026-09-20/marks.json).

A score is how many of the person's transitions an operator made within two
seconds — late, early, or never shown otherwise. The site lists each service with
its score; a service with no marks simply has not been reviewed yet.

**The current engine is not live-valid.** Its sung-slide rules use a music map and
a lyric/note alignment computed over the *whole* recording before replay begins —
knowledge of the future a live operator cannot have. Its results are stamped as
such everywhere they appear. Rebuilding those inputs from audio heard so far is the
next piece of work.

## Adding a service

Run the local server (it starts at login if you installed the launch agent) and
open **http://localhost:8791/intake/**. Give it the YouTube recording, the slides,
and the bulletin — local paths like `~/Downloads/092026 PowerPoint.pptx` work, as
do links that download the file directly. It builds the bundle in the background,
which takes several minutes (transcription and reading the sheet music), and opens
the marking harness when done.

From the command line, the same thing:

```bash
python3 -m slide_operator.training.ingest --youtube '<recording URL>' \
    --slides ~/Downloads/deck.pptx --bulletin ~/Downloads/bulletin.pdf
```

A bundle is `runs/<date>/`: the recording (`audio.webm`), the deck, the bulletin
(`folder.pdf` or `.docx`), a manifest (`bundle.json`), the marks, and the three
inputs every operator reads — the transcript, the OCR'd lyrics and the recognised
notes. Those are committed, the last three because they cannot be rebuilt
faithfully: Whisper transcribes the same audio differently on each run, and the
OCR and note recognition need tools only this Mac has. Everything else in the
directory is derived and rebuilt on demand.

## Marking a service

Open the service from **http://localhost:8791/** and play it. The large button reads
**Mark 8 → 9**: press it (or <kbd>M</kbd>) at the moment that transition should
happen. Your marks drive what is on screen, so slide 9 is up from then on and the
button moves on to **9 → 10**. The dropdown beside it follows your marks while the
audio plays; if the wrong slide is showing, or a slide should be skipped, choose the
pair there or click a slide under *Next & nearby*. <kbd>Esc</kbd> returns to
following. Notes go in the box beside it at any moment. Everything saves to
`marks.json` as you go.

The operator last replayed on the service appears as a separate track — its
transitions on the timeline and in a list, each timed against yours.

```bash
python3 -m slide_operator.training.score runs/2026-09-20     # score it from the shell
```

## Writing an operator

Anything that decides when the deck should move — the engine, Claude, another
model — is an operator: an object with two methods, run by
`slide_operator/training/runner.py`.

```python
prepare(pre, foresight)      # before the service: slides, OCR'd lyrics, recognised
                             # notes, bulletin, service map, SLIDE_OPERATOR.md
step(t, words, levels)       # every half second: the words a streaming recogniser
                             # has committed by time t, and the audio level so far
                             # -> a list of Decision(at, to, why)
```

Pre-reading the slides and bulletin is allowed; hearing ahead is not. The runner
owns the clock and hands `step` nothing from the future. An operator that needs
inputs computed from the whole recording must declare them in `foresight`; the
runner then supplies them through that separate argument and stamps the result as
not live-valid. Register it in `training/operators/` and replay it with

```bash
python3 -m slide_operator.training.runner runs/2026-09-20 --operator <name>
```

### Driving a real deck

```bash
# rehearse against the recording at 30x, deck in memory
python3 -m slide_operator.live --run runs/2026-09-20 --speed 30 --until 720

# script a person grabbing the keyboard at 10:00, to exercise the deference rules
python3 -m slide_operator.live --run runs/2026-09-20 --speed 30 --intervene 600:9

# drive PowerPoint for real, from the sound-board feed
python3 -m slide_operator.live --run runs/2026-09-20 --deck powerpoint \
    --audio device --asr live
```

The operator HUD is at `http://localhost:8792/`. **PowerPoint read-back and slide
control have not yet been verified against a running slide show** — treat the live
path as rehearsed, not proven.

### Publishing the showcase

```bash
python3 -m slide_operator.replay.site runs/2026-09-20      # -> docs/2026-09-20/
```

Each service gets its own directory under `docs/`, and the landing page at the root
is rebuilt to list them.

## Layout

| | |
|---|---|
| `slide_operator/ingest/` | deck, worship folder, sheet-music OCR, optical music recognition |
| `slide_operator/audio/` | music regions and tune period, forced alignment, note matching, voices |
| `slide_operator/prepare/` | folder↔deck correlation |
| `slide_operator/replay/` | the engine, the marking harness, the local server, the static site |
| `slide_operator/training/` | marks, the operator interface, runner and scorer, intake |
| `slide_operator/live/` | live harness, operator HUD, intervention rules |
| `slide_operator/deck_control/` | PowerPoint via AppleScript; an in-memory deck for testing |
| `runs/<date>/` | one service's bundle: recording, deck, bulletin, manifest and marks are committed; the rest is derived |
| `docs/` | the published site — a landing page plus one directory per service |

## Documents

- **[SLIDE_OPERATOR.md](SLIDE_OPERATOR.md)** — the specification. The engine reads
  its guard values out of this file, so editing the document changes behaviour.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — what each module does and how they fit.
- **[TESTING.md](TESTING.md)** — how a recorded service is replayed and scored.
- **[OPTIONS.md](OPTIONS.md)** — what was considered before building, and why.

## Requirements

macOS on Apple Silicon, mainly: transcription uses `mlx_whisper`, and the
sheet-music OCR calls the system Vision framework. Also `torchaudio` (forced
alignment), `homr` (optical music recognition), `PyMuPDF`, `python-pptx`,
`numpy`, `resemblyzer` (speaker embeddings), `ffmpeg`, and LibreOffice for
rendering slides to images.
