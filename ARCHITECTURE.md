# How this works

The system listens to a service and advances the slide deck. Its central idea is
that a slide operator does not transcribe what is said — they **follow printed
words**, and when a hymn starts they follow **printed music**. So the engine reads
the deck first and then listens for what it already expects to hear.

Two paths exist: a **replay harness** that runs a recorded service offline and
scores it against a human record, and a **live loop** that drives PowerPoint from
a soundboard feed. The replay path is well exercised; the live path runs
end-to-end against a recording but has never driven a real slide show.

## The pieces

```
INPUTS                 ANALYSIS                        DECISION            OUTPUT
deck.pptx  ─┬─► ingest/deck.py    ─► slides            ┐
            ├─► ingest/melody.py  ─► lyrics (OCR)      │
            └─► ingest/score.py   ─► notes (OMR)       │
folder.pdf ───► ingest/folder.py  ─► blocks            ├─► replay/run.py ─► decisions.json
                prepare/service_map.py ─► service map  │   (the engine)      │
audio.wav  ─┬─► asr/record.py     ─► words.jsonl       │                     │
            ├─► audio/music.py    ─► regions, tune     │   replay/oracle.py ─► sung spans
            ├─► audio/lyrics_align.py ─► lyric onsets  │   (feeds the aligner)│
            └─► audio/note_align.py   ─► note onsets   ┘                     ▼
                                          verdicts.json ─► replay/review.py ─► review page
                                        (the human record)
```

### Reading the inputs

| module | what it does |
|---|---|
| `ingest/deck.py` | Reads the .pptx. Per slide: title, body text, how many sheet-music strips, whether it is a **cover** (nothing to read), which **run** it belongs to (consecutive slides sharing a title = one element), and whether that run is **sung**. |
| `ingest/melody.py` | macOS Vision OCR of the sheet-music strips, because on this deck the lyrics exist only as pictures. Reads each strip twice — whole, and cropped to the lyric band — and keeps whichever recovers more words. |
| `ingest/score.py` | Optical music recognition (`homr`) of the same strips: the printed **notes**. |
| `ingest/folder.py` | The worship folder (.docx or .pdf) into ordered text blocks. No liturgical vocabulary is used anywhere. |
| `prepare/service_map.py` | Correlates folder against deck to find what each slide is, which elements are never displayed, which slides are covers, and what words release each cover. Diagnostic: the engine does not read its output. |

### Listening

| module | what it does |
|---|---|
| `asr/record.py` | Whisper transcription into timed words. Free recognition — it works on speech and fails on singing. |
| `audio/music.py` | Finds **music regions** (loud, sustained, few words), the tune's **period** by chroma self-similarity, a **stanza grid**, and where **singing actually starts**, distinct from where the music starts. An element begins where the level holds above the room's floor, not where it approaches the volume of full singing — that distinction is what keeps an organ introduction from being discarded as silence. |
| `audio/lyrics_align.py` | Forced alignment of the slide's *known* lyrics to the audio. This is the core trick: following printed words, not transcribing. |
| `audio/note_align.py` | Matches printed notes to notes actually sung (DTW). Notes place the boundary where slides carry different music; lyrics pick the stanza where every slide prints the same tune. |
| `audio/voices.py` | Speaker embeddings and clustering, so the display can say who is talking. Roles come from structure — who speaks longest, and where — never from what they say. |

### Deciding and checking

| module | what it does |
|---|---|
| `replay/run.py` | **The engine.** Walks the service forward in time, sees only what has happened so far, and decides when to advance. |
| `replay/oracle.py` | Builds sung spans non-causally so the aligner knows which stretch of audio holds which hymn. Its `reference.json` is machinery, **not** a yardstick — see TESTING.md. |
| `replay/verdicts.py` | **The evaluation.** Scores the engine against the human record. |
| `replay/review.py` | Builds the review page: audio, timeline, the slide on screen, the OCR text, every decision with its reason, and the marks. |
| `replay/serve.py` | Serves `runs/` and accepts the marks the review page writes back. |

## What the engine actually does

It holds a current slide and moves on positive evidence:

- **Words** — the next slide's opening heard in the transcript, or the current
  slide's closing words (a "handoff"). A slide is never treated as finished before
  its own text could plausibly have been read aloud; the creed prints "God the
  Father Almighty" in both its first line and its last, and without that guard the
  opening line retires the slide.
- **Music starting** — before singing begins, this means the spoken element is over
  and the next slide is due. This is what puts the offering slide up for its
  interlude.
- **Singing starting** — enters a sung element, at the introduction rather than the
  first sung word. A sung element is not abandoned for a different one before its
  own words are sung out.
- **Notes and lyrics** — inside a hymn these place each stanza boundary. A spoken
  last word is over as it is said; a sung one is held, so where the notes put the
  next stanza later than the lyric clock, the notes win.
- **Music stopping** — a sung element is over once its own words have been sung out.
- **Silence** — a slide whose text has been read out, followed by quiet, hands on.
  The collection is silent and no music starts until the offering hymn.

Guards throttle all of it: a minimum dwell per slide, a cooldown after each move,
a cap on moves per minute, and a much longer dwell on covers.

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

| module | what it does |
|---|---|
| `live/harness.py` | One pass: poll the deck, take newly heard words, measure the level, decide, push any move, publish state. |
| `live/hud.py` | The operator's display. |
| `live/intervention.py` | §8. Advance → resume at once; reverse → hold, or until a human advances. |
| `deck_control/powerpoint.py` | AppleScript to PowerPoint, using its own scripting vocabulary. |
| `deck_control/virtual.py` | A deck in memory that can be scripted to move by itself — the only way to test §8. |
| `audio/capture.py` | Sound-board input, or a recording replayed at wall-clock speed. |
| `asr/stream.py` | Transcription that only commits words two passes agree on. |
| `config.py` | Reads the guards out of `SLIDE_OPERATOR.md`, so editing the document changes behaviour. |

## What remains true

1. **Live runs a few seconds behind replay.** Streaming transcription commits at
   about 3.5 s, so live decisions land 2–4 s later than the same decisions made
   over a finished recording.
2. **PowerPoint read-back and `goto` are unverified.** The vocabulary came from
   PowerPoint's own dictionary and the app answers, but nothing has been tested
   against a running slide show.
3. **Sung precision depends on analysis prepared beforehand.** Notes, aligned
   lyrics and the music map are computed from a recording. Live, they must be built
   incrementally; until then the live engine leans on its word rules.
4. **Repeated text defeats alignment.** Where a hymn prints an identical refrain on
   four slides, forced alignment cannot say which repetition is being sung, and
   where it loses a hymn's opening stanza every later verse inherits the error.
   This is the largest known source of remaining mistakes.
