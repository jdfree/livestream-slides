# Backtesting Against Recorded Services

How to run the operating policy against a past livestream and find out whether it
is any good.

---

## The core idea: replay, don't listen

The naive approach — play a YouTube video at 1× into the live pipeline — is
faithful but useless for iteration. Every experiment costs 90 minutes, and you
will want hundreds of experiments.

Instead, **run the speech recognizer over the audio once and record its output as
a timestamped event log.** Then replay that log against a virtual clock as fast as
the machine allows. A 90-minute service replays in seconds, and every dwell timer,
timeout, and rate limit in §6 still behaves exactly as it would live, because they
all read the virtual clock rather than the wall clock.

The critical detail that makes this honest:

> Record **two** timestamps per recognized word: `audio_t` (where it occurs in the
> audio) and `commit_t` (when the streaming recognizer actually became confident
> enough to emit it). Replaying on `commit_t` reproduces streaming latency and
> streaming error characteristics faithfully.

Do **not** shortcut this by transcribing the file offline in one pass. Offline
Whisper sees the whole recording and is markedly more accurate than a streaming
recognizer that has only heard up to *now*. A policy tuned against offline
transcripts will look excellent in testing and disappoint live. Run the real
streaming recognizer once per service; cache its event log; replay forever.

YouTube's own auto-captions are fine for a first smoke test — they cost nothing —
but they are a different recognizer with different failure modes and no streaming
semantics. Do not tune anything against them.

---

## Pipeline

```
YouTube URL ──yt-dlp──> audio.wav ──streaming ASR (once)──> events.jsonl
worship folder.pdf ──PyMuPDF──> folder text ─┐
slide deck.pptx ──> slide text + slide PNGs ─┴──align──> service_map.json

              events.jsonl + service_map.json
                          │
                    replay runner (virtual clock)
                          │
                    ┌─────┴─────┐
              matcher      adjudicator (LLM, hard cases only)
                          │
                   virtual deck adapter
                          │
                  decisions.jsonl ──score──> report
                                      ▲
                              truth.jsonl (§ Ground truth)
```

### Proposed layout

```
slide_operator/
  ingest/     audio.py (yt-dlp)  folder.py (PDF)  deck.py (PPTX → text + PNGs)
  prepare/    slide_model.py     service_map.py   (§3 of the operating doc)
  asr/        stream.py          record.py        (emit + persist commit events)
  engine/     state.py  matcher.py  adjudicator.py  operator.py
  deck/       base.py   virtual.py  powerpoint.py
  replay/     clock.py  runner.py   truth.py  score.py
  console/    server.py                        (§12.1)
```

```bash
slide-operator ingest --youtube <url> --folder folder.pdf --deck deck.pptx --out runs/2026-06-15
slide-operator asr-record runs/2026-06-15     # slow, once per service
slide-operator truth      runs/2026-06-15     # ground truth from video, if available
slide-operator replay     runs/2026-06-15     # fast, repeatable
slide-operator score      runs/2026-06-15
```

Only `asr-record` and `truth` are slow. Everything you actually iterate on is fast.

---

## The virtual deck

The test double behind the same adapter interface as §13:

- records every `goto_slide` with its virtual timestamp;
- answers `get_current_slide` from its own state;
- **can be scripted to change slide on its own** at chosen times.

That last capability is the only way to test §8. Manual interventions never appear
in a recording, so inject them: advance a slide at a moment the engine did not
ask for, and assert that it detects the drift, adopts the new position, enters
DEFERENCE, and raises its evidence bar. Same for the two-interventions-in-five-
minutes path into HANDS_OFF. These are among the most important behaviors in the
whole document and the least likely to arise naturally in a replay.

---

## Ground truth

Metrics need to know when slides *actually* changed. The best source is the video
itself.

**If the livestream shows the projected slides in frame** — a dedicated slide
feed, picture-in-picture, or a camera that includes the screen — this is nearly
free and it makes the entire archive self-labeling:

1. Render every deck slide to a PNG during ingest.
2. Sample video frames at ~1 fps.
3. Match each frame against the rendered slides (perceptual hash, or template
   match on a cropped screen region).
4. Collapse runs of identical matches into transition timestamps.

Camera cuts to the pulpit will produce gaps. That is fine — **partial ground truth
is still good ground truth.** Each confident sample says "at time T the real slide
was N," which is all `time-on-wrong-slide` needs. Score over the sampled subset
and report coverage alongside the metric.

**If the slides never appear on camera**, fall back to labeling one service by
hand — play the audio, tap a key at each transition — and treat that single
labeled service as the calibration set. Slower, and it caps how many services you
can score, so check the video first.

Score against §12's metrics, weighting early errors 3× late ones as specified
there.

---

## What YouTube backtesting cannot test

Be clear-eyed about this before investing in a large corpus.

| Testable from a recording | Not testable |
|---|---|
| Anchor matching, evidence tiers, monotonic progression | **Channel separation (§2.1)** — an archive is one mixed stream |
| Cover-slide entry and release, service-map derivation | Real streaming latency under projector load |
| LOST detection and recovery | Live soundboard gain changes, feedback, channel dropout |
| Interventions and DEFERENCE (via injection) | Whether the deck adapter actually works on the booth machine |
| Stanza clock, structural evidence — **approximately** | |

The channel gap is the significant one. Everything in §2.1 assumes separate SPEECH
and MUSIC feeds, and a YouTube archive gives you only MIX. So backtesting exercises
the system in its *degraded* mode throughout. That is not wasted — MIX is a real
fallback path that deserves testing — but it means hymn tracking will look worse
in backtesting than it should live, and the channel-penalty rules go entirely
unexercised.

Two mitigations, in order of cost:

1. Accept it. Tune the policy on speech-driven elements, where the archive is
   representative, and defer channel tuning to live rehearsal.
2. Run source separation (e.g. Demucs) over the archive to synthesize approximate
   vocal and instrumental stems. Rough, but it lets the channel logic execute
   against something rather than nothing.

Either way, plan one live rehearsal with the real board before trusting §2.1.

---

## Keeping the doc and the code honest

The operating document is the specification, but the hybrid engine implements
parts of it in code — the guards, the tiers, the decision table. Those will drift
apart unless prevented.

- Keep every threshold in **one config file** that both the matcher and the
  adjudicator read, and treat §6's guard block as its source.
- Give the adjudicator the operating document **verbatim** in its prompt. It should
  reason from the same text a human reads, not from a paraphrase.
- When the §14 changelog records a threshold change, it changes in the config —
  and nowhere else.

---

## Self-improvement loop

After each scored replay, run a review pass: give an LLM the decision log, the
scored errors, and the current operating document, and ask it to propose §14
entries — what happened, which section governs it, the transcript evidence, and a
proposed rule change.

Keep this a **batch job between runs**, not something the engine does live. And
keep §14's rule: proposals are appended with evidence; thresholds change only when
a human promotes them. An agent that silently retunes its own guards mid-corpus
makes every earlier result unreproducible.

---

## Suggested order of work

1. **Ingest + prepare, on one service.** Get `service_map.json` out of a real folder and deck, and inspect it by hand. If the alignment is wrong, nothing downstream matters. This also exercises §3's sanity gate against a real PDF.
2. **Ground-truth spike.** Check whether the slides are visible in the video *before* building anything else — the answer determines how much of the archive is usable.
3. **Virtual deck + replay runner + matcher.** No LLM yet. Score it. This establishes the baseline the adjudicator has to beat.
4. **Adjudicator** on the §6 hard cases. Score again. If it does not measurably improve time-on-wrong-slide, that is worth knowing early.
5. **Intervention injection tests** (§8).
6. **Console**, once there is something worth watching.
7. Widen to the full archive; start the §14 loop.
