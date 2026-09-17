# How this works

Two things exist today. A **replay harness** that runs a whole recorded service
offline and scores it, and a **review page** for judging the result by ear. The
live system — the one that actually advances slides during a service — does not
exist yet. This document says exactly what is built, what each piece does, and
what is missing.

## The pieces

```
INPUTS                 ANALYSIS                        DECISION            OUTPUT
deck.pptx  ─┬─► ingest/deck.py    ─► slides            ┐
            ├─► ingest/melody.py  ─► lyrics (OCR)      │
            └─► ingest/score.py   ─► notes (OMR)       │
folder.pdf ───► ingest/folder.py  ─► blocks            ├─► replay/run.py ─► decisions.json
                prepare/service_map.py ─► service map  │   (the engine)      │
audio.wav  ─┬─► asr/record.py     ─► words.jsonl       │                     │
            ├─► audio/music.py    ─► regions, tune     │   replay/oracle.py ─► reference.json
            ├─► audio/lyrics_align.py ─► lyric onsets  │   (the yardstick)   │
            └─► audio/note_align.py   ─► note onsets   ┘                     ▼
                                                              replay/review.py ─► review page
```

### Reading the inputs

| module | what it does |
|---|---|
| `ingest/deck.py` | Reads the .pptx. Per slide: title, body text, how many sheet-music strips, whether it is a **cover** (nothing to read), which **run** it belongs to (consecutive slides sharing a title = one element), and whether that run is **sung**. |
| `ingest/melody.py` | macOS Vision OCR of the sheet-music strips, because on this deck the lyrics exist only as pictures. Reads each strip twice — whole, and cropped to the lyric band — and keeps whichever recovers more words. |
| `ingest/score.py` | Optical music recognition (`homr`) of the same strips: the printed **notes**. |
| `ingest/folder.py` | The worship folder (.docx or .pdf) into ordered text blocks. No liturgical vocabulary is used anywhere. |
| `prepare/service_map.py` | Correlates folder against deck to find what each slide is, which elements are never displayed (the sermon), which slides are covers, and what words release each cover. |

### Listening

| module | what it does |
|---|---|
| `asr/record.py` | Whisper transcription of the whole recording into timed words. Free recognition — it works on speech and fails on singing. |
| `audio/music.py` | Finds **music regions** (loud, sustained, few words), the **tune's period** by chroma self-similarity, a **stanza grid**, and where **singing actually starts** (distinct from where the music starts). |
| `audio/lyrics_align.py` | Forced alignment of the slide's *known* lyrics to the audio. This is what a person does — following printed words, not transcribing. |
| `audio/note_align.py` | Matches the printed notes to the notes actually sung (DTW), and combines notes with lyrics: notes place the boundary where slides carry different music, lyrics pick the stanza where every slide carries the same tune. |

### Deciding and checking

| module | what it does |
|---|---|
| `replay/run.py` | **The engine.** Walks the service forward in time, sees only what has happened so far, and decides when to advance. Also scores itself. |
| `replay/oracle.py` | **The yardstick.** Builds the reference timeline *non-causally* — it may look at the whole recording. It is not a competitor; it is the answer key. |
| `replay/review.py` | Builds the review page: audio, timeline, both slides side by side, the OCR text, every decision with its reason. |

## What the engine actually does

It holds a current slide and moves on positive evidence:

- **Words** — the next slide's opening heard in the transcript, or the current slide's closing words (a "handoff").
- **Music starting** — before singing begins, this means the spoken element is over and the next slide is due. This is what puts the offering slide up for its interlude.
- **Singing starting** — enters a sung element. Never at the first note: an introduction or interlude comes first.
- **Notes and lyrics** — inside a hymn, these place each stanza boundary.
- **Music stopping** — a sung element is over once its own words have been sung out.

Guards throttle all of it: a minimum dwell per slide, a cooldown after each move, a cap on moves per minute, and a much longer dwell on cover slides.

## Running it live

```bash
# rehearse against a recording, deck in memory, 30x speed
python3 -m slide_operator.live --run runs/2026-09-13 --speed 30 --until 720

# rehearse and watch a human take over at 10:50
python3 -m slide_operator.live --run runs/2026-09-13 --speed 30 --intervene 650:9

# drive PowerPoint for real, from the sound-board feed
python3 -m slide_operator.live --run runs/2026-09-13 --deck powerpoint \
    --audio device --asr live
```

The HUD is at http://localhost:8792/ — clock, the slide actually on the deck, what
is on screen and what is next, the level meter, who is speaking, the words just
heard, and every decision with its reason. When a person moves the deck back it
turns red and counts down the hold.

## The live loop

| module | what it does |
|---|---|
| `live/harness.py` | One pass: poll the deck, take newly heard words, measure the level, decide, push any move to the deck, publish state. |
| `live/hud.py` | The operator's display, served over plain HTTP. |
| `live/intervention.py` | §8. Advance → resume at once; reverse → hold `MANUAL_HOLD`, or until a human advances. |
| `deck_control/powerpoint.py` | AppleScript to PowerPoint, using its own scripting vocabulary. |
| `deck_control/virtual.py` | A deck in memory that can be scripted to move by itself — the only way to test §8. |
| `audio/capture.py` | Sound-board input, or a recording replayed at wall-clock speed. |
| `asr/stream.py` | Transcription that only commits words two passes agree on. |
| `config.py` | Reads the guards out of `SLIDE_OPERATOR.md`, so editing the document changes behaviour. |

## What remains true

1. **Live runs a few seconds behind replay.** Streaming transcription commits at
   about 3.5 s (12 s window, 2 s hop), so live decisions land 2–4 s later than the
   same decisions made over a finished recording.
2. **PowerPoint read-back and `goto` are unverified.** The vocabulary came from
   PowerPoint's own dictionary and the app answers, but nothing has been tested
   against a running slide show.
3. **Sung precision depends on analysis prepared beforehand.** Notes, aligned
   lyrics and the music map are computed from a recording. Live, they must be
   built incrementally; until then the live engine leans on its word rules.
4. **The reference shares sources with the engine.** In sung passages both consume
   the same notes and lyrics, so their agreement is partly circular. A listener is
   the only independent check.
