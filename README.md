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

Play the September 13 service and watch what it did: the timeline of music and
voices, the slide it had on screen at every moment, what it believed that slide
said, every transition with the reason it fired, and the human record it is graded
against.

## How it is graded

**By a person, not by itself.** Someone watched the service and marked 45 moments
— "at 21:17 verse 1 has ended, show verse 2", "at 44:02 the creed is not finished,
don't move yet". Those marks are the evaluation, committed as
[`runs/2026-09-13/verdicts.json`](runs/2026-09-13/verdicts.json).

It currently meets **26 of 45**. The system also builds a machine reference, but
that is not the yardstick and never appears in the score: it derives its sung
boundaries from the same alignment the engine reads, so agreeing with it proves
nothing. [TESTING.md](TESTING.md) explains why in more detail.

The largest remaining fault is repeated text. Where a hymn prints an identical
refrain on four slides, forced alignment cannot tell which repetition is being
sung; and where it loses a hymn's opening stanza, every later verse inherits the
error.

## Running it against a new service

Everything about one service lives in `runs/<date>/`. Create one and put the two
documents in it:

```bash
mkdir -p runs/2026-09-20
cp ~/Downloads/deck.pptx   runs/2026-09-20/deck.pptx
cp ~/Downloads/folder.pdf  runs/2026-09-20/folder.pdf     # .docx also accepted
```

Get the audio. Nothing in this repo downloads it — fetch the stream however you
normally would, then produce both files the pipeline expects:

```bash
yt-dlp -f bestaudio -o runs/2026-09-20/audio.webm '<livestream URL>'
ffmpeg -i runs/2026-09-20/audio.webm -ac 1 -ar 16000 runs/2026-09-20/audio.wav
```

Then run the pipeline. Only the first step is slow; everything you iterate on
replays a whole service in about a second.

```bash
python3 -m slide_operator.asr.record    runs/2026-09-20   # transcribe once (slow)
python3 -m slide_operator prepare       runs/2026-09-20   # folder <-> deck correlation
python3 -m slide_operator.replay.oracle runs/2026-09-20   # music, OMR, alignment
python3 -m slide_operator.replay.run    runs/2026-09-20   # the engine -> decisions.json
python3 -m slide_operator.replay.review runs/2026-09-20   # build the review page
python3 -m slide_operator.replay.serve  8791              # then open /2026-09-20/review/
```

`prepare` prints a sanity gate: if too little of the deck anchors to the folder it
says so, and you should look at why before trusting anything downstream.

### Judging it

Open the review page, play the service, and when a slide is wrong scrub to the
moment it *should* have changed, pick the slide and press **Mark**. Those marks
are written straight back to `runs/<date>/verdicts.json`. To score:

```bash
python3 -m slide_operator.replay.verdicts runs/2026-09-20
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
python3 -m slide_operator.replay.site runs/2026-09-20 docs
```

## Layout

| | |
|---|---|
| `slide_operator/ingest/` | deck, worship folder, sheet-music OCR, optical music recognition |
| `slide_operator/audio/` | music regions and tune period, forced alignment, note matching, voices |
| `slide_operator/prepare/` | folder↔deck correlation |
| `slide_operator/replay/` | the engine, the review page, the scorer, the static site |
| `slide_operator/live/` | live harness, operator HUD, intervention rules |
| `slide_operator/deck_control/` | PowerPoint via AppleScript; an in-memory deck for testing |
| `runs/<date>/` | one service. Only `verdicts.json` is committed — everything else is reproducible |
| `docs/` | the published site |

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
