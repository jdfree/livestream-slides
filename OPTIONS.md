# Build vs. buy

Surveyed 2026-08-16, before any code existed. The vendor-by-vendor charts have
been removed now that the choices are made and implemented; what follows is what
those choices were and why, so that revisiting one starts from the reasoning
rather than from scratch.

## Nothing on the market does this job

The church-AI products that exist solve a *different* problem: they listen for
Bible references and generate a verse slide on the fly. None of them follow a
prepared order-of-worship deck containing liturgy, lyrics and hold slides.

The closest behavioural prior art is not church software at all. PromptSmart's
VoiceTrack teleprompter scrolls a known script as you speak, stops when you
improvise, and resumes when you return to the text — almost exactly the wanted
behaviour, applied to a script rather than a deck. Mobile-only, no API: a
reference, not a dependency.

## What was chosen

| Layer | Decision | Why |
|---|---|---|
| Deck control | PowerPoint desktop, AppleScript, polled | Position **readback** is the only way to detect that a human grabbed the keyboard (§8), and PowerPoint gives it with zero change to how volunteers build the deck. ProPresenter has the better API but only matters if the building already runs it. |
| Transcription | Local Whisper; streaming with LocalAgreement | Cloud would reintroduce the one dependency this design otherwise avoids — church wifi holding up for 90 minutes — and would ship pastoral audio offsite. Cost was never the argument; it is cents either way. |
| Following engine | Deterministic, no LLM in the loop | Built as written. An LLM adjudicator for the hard cases was proposed and never needed: the hard cases turned out to be *evidence* problems, not *judgement* problems. Alignment and music structure resolved them. |
| Folder ingestion | Correlate folder against deck; no vocabulary | A curated liturgical-header parser works for one tradition and fails silently for the next. Deriving structure from folder↔deck correlation keeps the system portable to churches that name things differently. |
| Operator console | Local web page over plain HTTP | Viewable on the booth machine, a tablet or a second monitor. |

## The one that did not survive contact

Sung lyrics are the weakest link, and no vendor fixes it — word error rates on
singing are far worse than on speech for every engine surveyed. The original
response was to stop depending on those words and let a stanza clock carry hymns.
That helped, but what actually carries them is **forced alignment of the slide's
own printed lyrics** plus **DTW against the printed notes** — reading what is on
the slide rather than transcribing what is heard. Neither was in this survey.

## Still open

1. Can the board give a voice-only send separate from a music send? Everything in
   §2.1 assumes it; once summed it cannot be un-summed. Highest-value question.
2. Mac or Windows in the booth, and is there a GPU?
3. Is the projector extended or mirrored? Mirrored means the console needs a
   second device on the LAN.
