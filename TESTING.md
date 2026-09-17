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

## A run directory

Everything about one service lives in `runs/<date>/`:

| file | what it is |
|---|---|
| `audio.wav`, `audio.webm` | the recording |
| `deck.pptx`, `folder.pdf` | the two documents |
| `words.jsonl` | transcription, one timed word per line |
| `music.json` | music regions, tune period, stanza grid, where singing starts |
| `lyrics.json`, `notes.json` | OCR of the sheet-music strips; OMR of the same staves |
| `align.json`, `note_align.json` | where each slide's printed words and notes were heard |
| `service_map.json` | folder↔deck correlation, covers, un-slided elements |
| `decisions.json` | what the engine did, and why |
| `verdicts.json` | **the human record — the evaluation** |
| `review/` | the review page and rendered slide images |

Only the transcription, the OCR and the OMR are slow. Everything iterated on is
fast: the engine replays a whole service in about a second.

## Running it

```bash
python3 -m slide_operator prepare runs/2026-09-13      # folder <-> deck correlation
python3 -m slide_operator.replay.oracle runs/2026-09-13 # music, alignment, notes
python3 -m slide_operator.replay.run    runs/2026-09-13 # the engine -> decisions.json
python3 -m slide_operator.replay.review runs/2026-09-13 # build the review page
python3 -m slide_operator.replay.verdicts runs/2026-09-13  # score against the marks
python3 -m slide_operator.replay.serve 8791             # serve runs/ for review
```

Deleting a cached file regenerates it. Deleting `music.json` invalidates the
alignment that was built inside its regions, so delete `align.json`,
`note_align.json` and `reference.json` with it.

## What the score means

**The evaluation is `verdicts.json` — what a person watching the service said
belonged on screen.** Each mark is one unambiguous fact: at time *t*, slide *n*.
That single form covers both "change here" and "not yet", and both are graded the
same way: find the window during which the engine actually displayed that slide
and measure how far *t* falls outside it.

`reference.json` is **not** the measure. It is built non-causally to give the
aligner sung spans to work in, and it is wrong often enough that scoring against
it misleads: it smears identical refrains across a hymn, has listed slides out of
order, and derives its sung boundaries from the same alignment the engine reads —
so agreement with it is partly circular. It stays because the aligner needs it,
not because it judges anything.

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
