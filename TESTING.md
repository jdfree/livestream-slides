# Testing against a recorded service

## Replay, don't listen

Playing a recording at 1× into the live pipeline is faithful and useless: every
experiment costs ninety minutes. Instead the recogniser runs over the audio once
and its output is kept as a timestamped word log; the engine then replays that log
against a virtual clock as fast as the machine allows. A service replays in
seconds, and every dwell, cooldown and rate limit still behaves as it would live,
because they all read the virtual clock.

One caveat that has held up: offline transcription sees the whole recording and is
markedly more accurate than a streaming recogniser that has only heard up to
*now*. A policy tuned against offline transcripts will flatter itself. Live
decisions land roughly 2–4 s later than the same decisions made over a finished
recording, which is the gap streaming latency opens.

## A bundle

Everything about one service lives in `runs/<key>/`, where the key is its date and
location (`2026-09-20-st-peter-fort-collins`). The first nine files are the bundle
and are committed; the rest is derived from them and rebuilt on demand.

| file | what it is |
|---|---|
| `audio.webm` | the recording, 32 kbps mono |
| `deck.pptx`, `folder.pdf` | the slides and the bulletin |
| `bundle.json` | where they came from, and the service's title |
| `marks.json` | **the person's transition marks and notes — the labels** |
| `feedback.json` | comments on what an operator did, from its demo page |
| `words.jsonl` | transcription, one timed word per line — frozen, because Whisper never transcribes the same audio identically twice |
| `lyrics.json`, `notes.json` | OCR of the sheet-music strips; OMR of the same staves |
| `audio.original.*`, `audio.wav` | the download, and 16 kHz mono for analysis |
| `music.json` | music regions, tune period, stanza grid, where singing starts |
| `align.json`, `note_align.json` | where each slide's printed words and notes were heard |
| `service_map.json` | folder↔deck correlation, covers, un-slided elements |
| `decisions.json` | what the operator did, why, and any foresight it used |
| `decisions.<name>.json` | the same for any operator other than the engine |
| `review/` | the marking harness and rendered slide images |

Only the transcription, the OCR and the OMR are slow. Everything iterated on is
fast: an operator replays a whole service in about a second.

## Running it

```bash
python3 -m slide_operator.training.ingest --youtube URL --slides PATH --bulletin PATH
python3 -m slide_operator.training.runner runs/2026-09-20-st-peter-fort-collins   # replay the engine
python3 -m slide_operator.training.score  runs/2026-09-20-st-peter-fort-collins   # score against the marks
python3 -m slide_operator.replay.review   runs/2026-09-20-st-peter-fort-collins   # rebuild the harness page
python3 -m slide_operator.replay.serve    8791              # services, intake, marking, demo
```

Deleting a cached file regenerates it. Deleting `music.json` invalidates the
alignment that was built inside its regions, so delete `align.json`,
`note_align.json` and `reference.json` with it.

## What the score means

**The labels are the transitions in `marks.json`**: at time *t* the deck should
leave slide *f* and show slide *g*. For each, the scorer finds when the operator put
*g* on screen, nearest to *t*. Within two seconds either way is a hit; otherwise it
was late or early by that much, or *g* was never shown. Notes are not scored.

This is stricter than the marks it replaced, which said only "slide *g* belongs on
screen at *t*" and so credited an operator that reached *g* early and was still on
it. Arriving early is an error, and now counts as one.

An operator that declared foresight gets a score stamped **not live-valid**. The
engine does: its music map and lyric/note alignment are computed over the whole
recording.

`reference.json` is **not** a measure. It is built non-causally to give the aligner
sung spans to work in, and stays only because the aligner needs it.

## What replay cannot test

| Testable from a recording | Not testable |
|---|---|
| Anchor matching, evidence tiers, monotonic progression | **Channel separation (§2.1)** — an archive is one mixed stream |
| Cover entry and release, service-map derivation | Real streaming latency under projector load |
| Recovery from a lost position | Soundboard gain changes, feedback, channel dropout |
| Interventions (by scripting the virtual deck) | Whether the deck adapter works on the booth machine |
| Stanza timing, structural evidence — approximately | |

The channel gap is the significant one: §2.1 assumes separate speech and music
feeds, and an archive gives only the mix, so backtesting exercises the system in
its degraded mode throughout. Hymn tracking should look worse here than live.
Plan one rehearsal with the real board before trusting any of §2.1.

Manual interventions never appear in a recording either, so they are injected:
`deck_control/virtual.py` can be scripted to change slide on its own at a chosen
moment, which is the only way to exercise §8.
