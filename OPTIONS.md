# Build vs. Buy — Options Considered

Research date: 2026-08-16. Prices and API details should be re-verified before committing.

## Headline finding

**Nothing on the market does this job.** The church-AI products that exist all
solve a *different* problem: they listen for Bible references and generate a
verse slide on the fly. None of them follow a prepared order-of-worship deck
containing liturgy, lyrics, and hold slides.

The closest behavioral prior art is not church software at all — it is
**PromptSmart's VoiceTrack** teleprompter engine, which scrolls a known script as
you speak, stops when you improvise, and resumes when you return to the text.
That is almost exactly the behavior we want, applied to a scrolling script rather
than a slide deck. It ships as a mobile app with no API, so we can borrow the
idea but not the code.

Practical consequence: **buy the transcription, buy the deck control, build the
following engine and the operator console.** Those last two are where all the
actual product is, and they are also the two pieces this project cares most about.

---

## The five layers

The problem separates cleanly, which is good news — each layer can be chosen and
swapped independently.

| Layer | Job | Verdict |
|---|---|---|
| **A. Deck control** | Read the current slide; go to a slide | Buy / adapt |
| **B. Transcription** | Live audio → text, low latency | Buy or self-host |
| **C. Following engine** | Decide when to advance | **Build** |
| **D. Folder ingestion** | PDF → service map, by correlation with the deck | **Build** |
| **E. Operator console** | Show reasoning; later, accept instructions | **Build** |

---

## Chart 1 — Turnkey and near-turnkey products

| Product | What it actually does | Follows *our* deck? | Notes |
|---|---|---|---|
| **[Pewbeam](https://pewbeam.com/)** | Real-time speech → detects Bible references (incl. paraphrase, via semantic search) → displays the verse | **No** | Verse projection only. Runs offline, NDI output. Free / $14 / $30 per mo. No documented API. Closest thing to a competitor, but a different product. |
| **[Loghema](https://www.loghema.com/)** (was LogosAI) | Verse detection, plus a lyrics workflow and AI sermon notes | **No** | Standalone presenter — it *imports* from ProPresenter/EasyWorship rather than driving them. Adopting it means abandoning your deck. Win/Mac, ~$14/mo intl. |
| **[WayPresenter](https://waypresenter.com/)** | AI verse detection and queueing | **No** (unverified) | Site returned 403 to automated fetch; assessment is from search results only. Same product category as the above. |
| **[WordCast Live](https://www.wordcastlive.site/)** | Church presentation + AI transcription | **No** (unverified) | Appears transcription/captioning oriented. |
| **[EasyWorship](https://blog.easyworship.com/2019/08/14/how-to-auto-advance-song-lyric-slides-with-audio-tracks/) auto-advance** | Lyrics advance on cue with an attached backing track | **No** | Timer/track-cue driven, not listening. Useless for live singing or spoken liturgy. |
| **[WorshipTools](https://faith.tools/app/318-worshiptools) / Worship Player auto-advance** | Auto-advance on timers | **No** | Same limitation. |
| **[PromptSmart Pro](https://promptsmart.com/how-it-works)** (VoiceTrack) | Teleprompter that tracks your voice through a known script, offline | **Behaviorally yes, mechanically no** | The right model for §1/§7 of the operating doc. Patented, mobile-only, no API. Reference, not a dependency. |

**Read:** the market has converged on "generate a verse slide from speech." Nobody
is doing "track position within a prepared service." That's a real gap, and it's
the gap this project sits in.

---

## Chart 2 — Layer A: deck control and position readback

This is the most consequential choice, because **position readback is the only
way to detect that a human grabbed the keyboard** (§8 of the operating doc). A
target without readback disqualifies the core requirement.

| Target | Read current slide? | Change push? | Go to slide | Workflow disruption | Verdict |
|---|---|---|---|---|---|
| **PowerPoint desktop (macOS)** | **Yes** — `current show position of slide show view of slide show window of active presentation` (AppleScript) | No — poll | Yes, set the same property | **None** — keep authoring .pptx exactly as today | **Recommended if the deck is a .pptx** |
| **PowerPoint desktop (Windows)** | **Yes** — `SlideShowWindows(1).View.Slide.SlideIndex` (COM/VBA) | No — poll | `View.GotoSlide n` | **None** | Equally good; pick by which OS runs the booth machine |
| **[ProPresenter 7](https://jeffmikels.github.io/ProPresenter-API/Pro7/)** | **Yes** — `presentationSlideIndex` over the remote WebSocket | **Yes** — subscribe, no polling needed | `presentationTriggerIndex` | **High** — the service must be rebuilt as ProPresenter presentations weekly | Technically the best API by a wide margin. Only worth it if the church already runs ProPresenter. |
| **[FreeShow](https://freeshow.app/api)** (open source) | Yes — `get_slide`, `get_output_slide_text` over Socket.IO :5505 | Not documented — assume poll | `index_select_slide`, `next_slide` | High — new presenter software | Good API, free, actively developed. Consider only if changing presenters anyway. |
| **[OpenLP](https://manual.openlp.org/web_remote.html)** (open source) | Probably — REST web remote + websockets, but **the manual documents the UI, not the endpoints** | Unknown | Probably | High | Would require reading source to confirm. Unquantified risk; not worth it unless already in use. |
| **Google Slides (browser)** | **Not via the API.** The Slides API reads deck *content*, not presenting position. Only observable via the presenting URL fragment / DOM | Via DOM observer | Via keystroke or URL | Low if decks are already in Slides | Workable through browser automation, but position sensing rests on undocumented DOM structure that Google can change. Fragile. |
| **Self-rendered HTML deck** (reveal.js et al.) | **Trivially** — we own the renderer | **Yes**, native events | Yes | Medium — weekly .pptx → HTML conversion step | The dark horse. Only option where **the deck and the operator console are one application**, which makes Layer D nearly free. Cost is a weekly conversion that must never break on a Sunday morning. |
| **Keynote** | Likely via AppleScript | No | Likely | — | Not investigated; flag if relevant. |

**Read:** PowerPoint desktop is the pragmatic winner *if* that's what the booth
already runs — full readback, zero change to how volunteers build the deck. The
lack of change-push doesn't matter; polling at 2 Hz is cheap and §4 only asks for
0.5 Hz. ProPresenter is the better engineering target but only if it's already in
the building.

---

## Chart 3 — Layer B: real-time transcription

Roughly 90 minutes per service, once or twice a week.

| Option | Latency | Runs offline | Cost shape | Notes |
|---|---|---|---|---|
| **[Deepgram](https://deepgram.com/learn/deepgram-vs-assemblyai-vs-whisper) Nova-3 / Flux** | Lowest measured end-of-speech latency (May 2026) | No | Per-minute, cents per service | Best-in-class streaming. Strong on meeting-style audio. |
| **ElevenLabs Scribe v2 Realtime** | ~150 ms first partial | No | Per-minute | Fastest first-partial figure found. |
| **[AssemblyAI](https://www.assemblyai.com/blog/best-api-models-for-real-time-speech-recognition-and-transcription) Universal streaming** | ~760 ms time-to-final | No | Per-minute; managed Whisper-Streaming ~$0.30/hr | Also sells a managed streaming-Whisper if we'd rather not run it. |
| **Speechmatics Melia-1** | — | **On-prem available** | License | Led aggregate WER (6.4%) in the cited benchmark. |
| **[whisper_streaming](https://aclanthology.org/2023.ijcnlp-demo.3.pdf) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper)** | ~500–800 ms partials; 3.3 s on unsegmented long-form | **Yes** | Free + hardware | LocalAgreement policy: re-runs Whisper on a growing buffer, commits words only when consecutive runs agree. Conservative by construction — a good match for our "prefer late" bias. |
| **[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) / WhisperLive** | Similar | **Yes** | Free + hardware | Packages VAD and diarization around the same idea. Diarization could distinguish pastor from congregation — useful for RESPONSIVE slides. |

**Read:** **local, settled.** Everything runs on the one booth machine, so cloud
transcription would reintroduce the single dependency this architecture otherwise
avoids — church wifi holding up for 90 minutes. Cost was never the argument
(cloud is cents per service); resilience and not shipping pastoral audio offsite
are. Keep a cloud provider behind the same interface for backtesting accuracy
comparisons only.

### Two channels, one machine

The soundboard gives us separate speech and music sends, which is a real
advantage — but running two full ASR streams on the machine that is also driving
the projector is the wrong way to spend it.

**Asymmetric treatment is much cheaper and probably better:**

| Channel | Processing | Why |
|---|---|---|
| **SPEECH** | Full streaming ASR, best model that fits | This is where nearly all reliable evidence lives — liturgy, off-slide cues, sermon boundaries. Worth the CPU. |
| **MUSIC** | Energy/VAD/onset analysis; ASR only opportunistically | We mostly need *structure* from this channel — music region start/end, stanza boundaries — and structure is nearly free to compute. Sung-word ASR is unreliable enough (§2.1) that paying full price for it buys little. |

Sung lyrics are the weakest link in the whole system and no vendor fixes it —
word error rates on singing are far worse than on speech, for every engine
surveyed. The operating doc's response is to stop depending on those words: the
stanza clock plus boundary detection (§5.1, §6) carries hymns instead. Opportunistic
lyric matches, when they do arrive, are a bonus that confirms position rather than
the mechanism that drives it.

**Sizing constraint:** the projector's rendering outranks transcription latency.
A dropped frame is visible to the congregation; 200 ms of extra ASR lag is not.
Measure ASR under projector load before trusting any model choice.

---

## Chart 4 — Layer C: the following engine

| Approach | Latency | Cost | Quality of on-screen reasoning | Verdict |
|---|---|---|---|---|
| **LLM sees every transcript chunk** | Seconds per decision | ~2,700 calls per service at 2 s chunks | Excellent | Too slow and too expensive to run continuously. |
| **Deterministic fuzzy matcher** (rapidfuzz + monotonic constraint + dwell guards) | Milliseconds | Zero | Poor — emits scores, not explanations | Handles the easy 90% perfectly, but can't produce the reasoning log you want. |
| **Hybrid: matcher decides, LLM adjudicates** | Milliseconds normally; seconds only when it matters | Tens of calls per service | Excellent where it counts | **Recommended.** |
| **Online forced alignment** (whisperX, aeneas are offline; online variants are research-grade) | — | — | — | Rejected: these align a *complete* transcript to a *complete* script. We have neither in real time. |

### The recommended hybrid

The deterministic matcher owns the routine case: a VERBATIM or LYRIC slide with a
clean anchor hit, adjacent transition, all §6 guards satisfied. It advances in
milliseconds for free.

The LLM is invoked only on the hard cases, which are exactly the cases the
operating doc spends its pages on:

- releasing a **HOLD** slide (sermon over? or just a long pause?)
- entering or recovering from **LOST**
- any non-adjacent jump
- interpreting a **human intervention** — what did they know that we didn't?
- multi-slide ambiguity the matcher can't break

This is also what makes Layer D work. A fuzzy matcher can print
`slide 12→13, score 0.83`. Only the LLM can write *"Sermon appears to have ended —
heard the closing 'Amen' followed by the first line of the offering hymn.
Advancing."* Since the LLM is already the component handling every interesting
moment, the console gets a readable narration of precisely the decisions a human
would want to second-guess, and nothing is spent narrating the boring ones.

---

## Chart 5 — Layer D: worship folder ingestion

The folder is a PDF whose layout varies without limit across churches — St. Peter
is the first test site, not the only target. This rules out the obvious approach.

**Rejected: a curated liturgical-header parser.** Recognizing `Confession`,
`Prayer of the Day`, `First Reading` and friends works for one tradition and fails
silently for the next. Every denomination names things differently, and churches
redesign their folders. It is the wrong abstraction for a multi-church product.

**Chosen: derive everything from folder↔deck correlation** (§3 of the operating
doc). Align the two documents monotonically, let the gaps in the alignment reveal
the un-slided elements, and take element names from adjacent unmatched lines
without interpreting them. No liturgical vocabulary anywhere in the system.

That leaves only one thing to buy: text extraction good enough to align.

| Option | Handles columns | Scanned PDFs | Notes |
|---|---|---|---|
| **PyMuPDF (fitz)** | Yes — exposes text blocks with coordinates, so reading order can be reconstructed | No | Fast, permissively usable, best control over layout. Strongest default. |
| **pdfplumber** | Yes — word-level coordinates | No | Slower, very good for inspecting *why* an extraction went wrong. Useful during the sanity gate. |
| **markitdown** | Partially | No | Convenient, but discards the coordinates needed to fix column order. |
| **pdftotext `-layout`** | Roughly | No | Zero-dependency fallback; fine when layout is simple. |
| **OCR (Tesseract / OCRmyPDF)** | Via layout analysis | **Yes** | Only path for image-only folders. Slow and lossy — run it ahead of Sunday, never live. |

**Read:** PyMuPDF as the primary, with coordinate-aware column reconstruction,
pdfplumber for diagnostics, and OCR as an explicit pre-service fallback. The
extraction is only ever as good as the sanity gate that checks it, which is why
that gate is a hard blocker in the operating doc rather than a warning.

**Note on fetching:** St. Peter's folders are reachable through a public
JSON:API, but per-church fetch integrations don't generalize. Design the system to
take *a PDF*, and treat any automated retrieval as a site-specific convenience
bolted on the outside.

---

## Chart 6 — Layer E: operator console

Requirement: a screen showing the AI's major reasoning, visible to whoever might
intervene. Later, an input box for typed instructions.

| Option | Effort | Reasoning display | Future instruction input | Notes |
|---|---|---|---|---|
| **Local web app** (FastAPI + WebSocket + plain HTML) | Low | Full | Natural — one more WebSocket message type | **Recommended.** Viewable on the booth machine, a tablet, or a second monitor. Same transport serves both directions. |
| **Terminal UI** (Textual/Rich) | Lowest | Good | Yes | Fine for development; poor for a volunteer glancing over at it. |
| **OBS overlay / stage display** | Medium | Limited | No | Read-only by nature; wrong shape for a two-way feature. |
| **Part of a self-rendered HTML deck** | Low *if* Layer A is already the HTML deck | Full | Natural | Only attractive if we pick the self-rendered deck in Chart 2. |

Design note: build the console against the **state variables already defined in
§4** of the operating doc — `actual_slide`, `believed_slide`, `mode`,
`audio_quality` — plus a scrolling reasoning log. Instruction input should land in
the same evidence pipeline as a human keystroke: a typed instruction is a Tier A
signal and should trigger DEFERENCE exactly as a manual advance does.

---

## Recommendation

1. **Layer A:** PowerPoint desktop via AppleScript or COM, polled at 2 Hz — assuming the Sunday deck is a .pptx. Zero disruption to whoever builds it each week.
2. **Layer B:** whisper_streaming or WhisperLiveKit, local; full ASR on SPEECH, cheap structural analysis on MUSIC. Cloud kept behind the same interface for backtesting comparisons only.
3. **Layer C:** deterministic matcher for routine advances; LLM adjudication for cover-slide releases, LOST recovery, jumps, and interventions.
4. **Layer D:** PyMuPDF extraction feeding a monotonic folder↔deck alignment. No liturgical vocabulary anywhere — element names are carried through as labels, never interpreted.
5. **Layer E:** local web app over WebSocket, built on §4's state variables.

Everything in Charts 2 and 3 sits behind the adapter contract in §13 of the
operating doc, so any of these can be swapped after testing without touching the
following engine.

---

## Open questions

Ordered by how much they'd change the plan.

**Settled:** soundboard feed (not a room mic); single machine running audio in,
deck out to projector, and console; local transcription; internet not on the
critical path. **St. Peter is the first test site, not the only target** — the
worship folder is an arbitrarily formatted PDF, and folder↔deck correlation is the
only structural assumption the system may make.

**Portability consequence:** the multi-church scope raises the cost of a
site-specific deck adapter. PowerPoint is still the right first target, but Layer
A should sit behind the §13 adapter interface from day one rather than being
assumed away — a second church running ProPresenter or Google Slides shouldn't
touch anything above that boundary.

1. **Can the board give us a voice-only aux/matrix send, separate from a music send?** This is now the highest-value open question. Any digital board can do it, and it's the difference between §2.1's channel rules working and falling back to a summed MIX where the band buries the liturgy. Once summed, it cannot be un-summed. **Ask the sound tech before anything else.**
2. **What projects the slides today, and what format is the deck authored in?** Decides Chart 2 outright — and PowerPoint desktop only wins if the deck is already a .pptx.
3. **Mac or Windows, and is there a GPU?** Decides AppleScript vs. COM, and whether the SPEECH-channel model can be a large one without competing with the projector.
4. **Is the projector an extended display or mirrored?** Extended means the console lives on the built-in screen for free. Mirrored means it needs a second device on the LAN, which is a meaningfully bigger build.
5. **What audio interface is available**, and how many discrete input channels can reach the machine?
