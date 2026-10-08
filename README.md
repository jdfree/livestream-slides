# Slide operator

Machine learning that listens to a church service and advances the slide deck —
the job a volunteer does from the back of the room, clicking at the right moment
for ninety minutes.

The current version, **ML1**, uses machine-learning models to hear and to read —
Whisper for speech, macOS Vision for the lyrics printed in sheet music, homr for
the printed notes, speaker embeddings for voices — and hand-written rules to
decide when to advance. Your marks are its labels and its measure; nothing yet
learns from them directly.

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
service in [`runs/<key>/marks.json`](runs/2026-09-20-st-peter-fort-collins/marks.json).

A score is how many of the person's transitions an operator made within two
seconds — late, early, or never shown otherwise. The site lists each service with
its score; a service with no marks simply has not been reviewed yet.

**ML1 is not live-valid.** Its sung-slide rules use a music map and
a lyric/note alignment computed over the *whole* recording before replay begins —
knowledge of the future a live operator cannot have. Its results are stamped as
such everywhere they appear. Rebuilding those inputs from audio heard so far is the
next piece of work.

## Adding a service

Run the local server (it starts at login if you installed the launch agent) and
open **http://localhost:8791/intake/**. Give it the YouTube recording, the slides,
the bulletin and the location (it starts as *St Peter, Fort Collins*) — local paths
like `~/Downloads/092026 PowerPoint.pptx` work, as do links that download the file
directly. It builds the bundle in the background, which takes several minutes
(transcription and reading the sheet music), and opens the marking harness when done.

A service is its date and location: `runs/2026-09-20-st-peter-fort-collins/`.
Uploading one that already exists — a corrected deck, a better recording — replaces
its media and everything derived from them, and keeps its marks and feedback byte
for byte. The new bundle is built beside the old one and swapped in only when it is
complete, so a failed upload changes nothing.

From the command line, the same thing:

```bash
python3 -m slide_operator.training.ingest --youtube '<recording URL>' \
    --slides ~/Downloads/deck.pptx --bulletin ~/Downloads/bulletin.pdf \
    --location 'St Peter, Fort Collins'     # the default
```

A bundle is `runs/<key>/`: the recording (`audio.webm`), the deck, the bulletin
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
`marks.json` as you go. The page reads the file each time it opens, and a save from
a tab opened before a newer save is refused rather than allowed to overwrite it.

The operator last replayed on the service appears as a separate track — its
transitions on the timeline and in a list, each timed against yours.

```bash
python3 -m slide_operator.training.score runs/2026-09-20-st-peter-fort-collins     # score it from the shell
```

## Watching an operator

Each service also has a **Demo** page: an operator's run played back — the slide it
had on screen at every moment, every decision and why — against your marks, each
shown on time, late, early or never shown, and with the status line saying where
your marks disagree with what is on screen. Choose the operator there, **Run again**
to replay it after changing it, and add **feedback** pinned to a moment (<kbd>F</kbd>).
Feedback goes to `feedback.json`, separate from the marks: it is about what one
operator did, not about what should happen, and it records which slide that
operator was showing.

## Writing an operator

Anything that decides when the deck should move — ML1, Claude, another
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
python3 -m slide_operator.training.runner runs/2026-09-20-st-peter-fort-collins --operator <name>
```

Two are registered. **ML1** is the rule engine above. **Jev** asks TypeSafe's
decision model one closed question each second or so — stay, next, or skip — with
the decision table of `SLIDE_OPERATOR.md` condensed into its instructions, the
slide on screen and the two after it, what has been heard since it went up, what
the sound is doing, and the pace of the hymn so far. It uses no foresight, and its
own response time is charged to its timing. A whole service is about 3,300 calls
and roughly $0.11. It needs `TYPESAFE_API_KEY`, which `.secrets` maps to
`James/TypeSafe API Key` in Bitwarden:

```bash
secrets run -- python3 -m slide_operator.training.runner \
    runs/2026-09-20-st-peter-fort-collins --operator Jev --until 600   # first 10 minutes
```

The demo page's **Run** button does the same for a whole service, and shows each
run's calls, cost and response times beside its score.

### Driving a real deck

```bash
# rehearse against the recording at 30x, deck in memory
python3 -m slide_operator.live --run runs/2026-09-20-st-peter-fort-collins --speed 30 --until 720

# script a person grabbing the keyboard at 10:00, to exercise the deference rules
python3 -m slide_operator.live --run runs/2026-09-20-st-peter-fort-collins --speed 30 --intervene 600:9

# drive PowerPoint for real, from the sound-board feed
python3 -m slide_operator.live --run runs/2026-09-20-st-peter-fort-collins --deck powerpoint \
    --audio device --asr live
```

The operator HUD is at `http://localhost:8792/`. **PowerPoint read-back and slide
control have not yet been verified against a running slide show** — treat the live
path as rehearsed, not proven.

### Publishing the showcase

```bash
python3 -m slide_operator.replay.site runs/2026-09-20-st-peter-fort-collins      # -> docs/2026-09-20-st-peter-fort-collins/
```

Each service gets its own directory under `docs/`, and the landing page at the root
is rebuilt to list them.

## Layout

| | |
|---|---|
| `slide_operator/ingest/` | deck, worship folder, sheet-music OCR, optical music recognition |
| `slide_operator/audio/` | music regions and tune period, forced alignment, note matching, voices |
| `slide_operator/prepare/` | folder↔deck correlation |
| `slide_operator/replay/` | ML1's rules (`run.py`), the marking harness, the local server, the static site |
| `slide_operator/training/` | marks, the operator interface, runner and scorer, intake |
| `slide_operator/live/` | live harness, operator HUD, intervention rules |
| `slide_operator/deck_control/` | PowerPoint via AppleScript; an in-memory deck for testing |
| `runs/<key>/` | one service's bundle: recording, deck, bulletin, manifest, marks and feedback are committed; the rest is derived |
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
