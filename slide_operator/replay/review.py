"""The marking harness: listen to a service and mark every transition.

    python -m slide_operator.replay.review runs/<key>
    python -m slide_operator.replay.serve 8791      # then open /<key>/review/

The person is the operator here. Their own transition marks drive what is on
screen: press **Mark 8 → 9** and slide 9 is up from that moment, and replaying
follows the marks. Beside the button, a dropdown names the pair the button will
record — it follows the marks while the audio runs, and can be set by hand (or by
clicking a nearby slide) when the wrong slide is showing or one is skipped. Notes
can be added at any moment.

Everything goes into runs/<key>/marks.json (training/marks.py). The page reads
that file when it opens rather than carrying a copy, and each save names the
version it started from, so a tab left open cannot write over newer marks. Whatever operator
was last replayed (training/runner.py) appears as a separate comparison track: its
transitions, timed against the person's.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..ingest import deck as deck_mod

SLIDE_WIDTH = 960


def render_slides(run: Path, out: Path, expect: int = 0) -> int:
    """Render the deck to one PNG per slide via LibreOffice. Cached.

    Cached on count, not merely on presence: a reloaded deck that gains a slide
    left the old images in place and the page showed the wrong picture for every
    slide after the insertion.
    """
    out.mkdir(parents=True, exist_ok=True)
    existing = sorted(out.glob("*.png"))
    if existing and (not expect or len(existing) == expect):
        return len(existing)
    for old in existing:
        old.unlink()
    import fitz

    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    with tempfile.TemporaryDirectory() as tmp:
        # A private profile keeps an already-open LibreOffice from swallowing the job.
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/profile", "--headless",
                        "--convert-to", "pdf", "--outdir", tmp, str(run / "deck.pptx")],
                       check=True, capture_output=True, timeout=600)
        pdf = fitz.open(str(Path(tmp) / "deck.pdf"))
        for i, page in enumerate(pdf, start=1):
            zoom = SLIDE_WIDTH / page.rect.width
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(str(out / f"{i:03d}.png"))
        return pdf.page_count


def build(run: Path) -> Path:
    review = run / "review"
    slides = deck_mod.load(run / "deck.pptx")
    n = render_slides(run, review / "slides", len(slides))
    if n != len(slides):
        print(f"warning: rendered {n} pages for {len(slides)} slides; images may be offset")
    from ..audio import music as music_mod
    from ..ingest import melody as melody_mod
    melody_mod.attach(slides, run / "deck.pptx", run / "lyrics.json")
    music = music_mod.analyze(run)          # for the reviewer's timeline only
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    dpath = run / "decisions.json"
    dec = json.loads(dpath.read_text()) if dpath.exists() else None
    vspath = run / "voices.json"
    voices = json.loads(vspath.read_text())["segments"] if vspath.exists() else []
    data = {
        "run": run.name,
        "audio": "../audio.webm",
        "save": "../marks.json",
        "first": slides[0].index,
        "slides": [{"index": s.index, "title": s.title, "img": f"slides/{s.index:03d}.png",
                    "cover": s.is_cover,
                    # what the system believes is on the slide: OCR of the sheet
                    # music, or the slide's own body text
                    "text": (s.lyrics or s.body).replace("\n", " ")[:400],
                    "src": "sheet-music OCR" if s.lyrics else "slide text"}
                   for s in slides],
        "operator": None if dec is None else {
            "name": dec.get("operator", "ML1"),
            "foresight": dec.get("foresight", []),
            "moves": dec["moves"]},
        "music": [[r["t0"], r["t1"]] for r in music["regions"]],
        "voices": [[v["t0"], v["t1"], v["role"], v["mode"]] for v in voices],
        "words": [[w["start"], w["w"]] for w in words],
    }
    payload = json.dumps(data).replace("</", "<\\/")
    page = review / "index.html"
    page.write_text(PAGE.replace("__DATA__", payload))
    return page


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marking harness</title>
<style>
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e0e0da;--ok:#2f9e5b;--bad:#d64545;--warn:#c98a2f;--unk:#c9c9c2;--accent:#3b6fd6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecece8;--muted:#9a9a94;--line:#34342f;--unk:#4a4a45}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,system-ui,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
h1{font-size:18px;margin:0} h1 a{color:var(--muted);text-decoration:none;font-weight:400}
.tiles{display:flex;gap:8px;flex-wrap:wrap}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;color:var(--muted);font-size:12px}
.tile b{display:block;font-size:18px;color:var(--ink)}
.tile.warn{border-color:var(--warn)} .tile.warn b{color:var(--warn);font-size:13px}
.guide{color:var(--muted);margin:10px 0}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
audio{flex:1;min-width:240px}
button,select,input{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 10px}
button{cursor:pointer} button.on{border-color:var(--accent);color:var(--accent)}
button:disabled{opacity:.45;cursor:default}
#timeline{width:100%;height:64px;display:block;margin-top:10px;cursor:pointer;background:var(--card);border:1px solid var(--line);border-radius:8px}
.legend{color:var(--muted);font-size:12px;margin:4px 0 12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
.marker{position:sticky;top:0;z-index:5;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}
#markBtn{background:var(--ok);border-color:var(--ok);color:#fff;font-size:17px;font-weight:600;padding:8px 18px;border-radius:8px;min-width:170px}
#markBtn.flash{filter:brightness(1.25)}
#pair{min-width:260px;max-width:100%}
#noteText{flex:1;min-width:200px}
.pill{font-size:11px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.pill.manual{color:var(--warn);border-color:var(--warn)} .pill.auto{color:var(--ok);border-color:var(--ok)}
.pill.ok{color:var(--ok);border-color:var(--ok)} .pill.bad{color:var(--bad);border-color:var(--bad)} .pill.note{color:var(--warn);border-color:var(--warn)}
#saveState{margin-left:auto;font-size:12px;color:var(--muted)}
#saveState.err{color:var(--bad)}
.status{font-weight:600;margin-bottom:8px}
.who{display:inline-block;margin-left:10px;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:var(--card);color:var(--muted);font-weight:400}
.stage{display:grid;grid-template-columns:2fr 1fr;gap:12px}
.pane{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;min-width:0}
.pane h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 6px;display:flex;justify-content:space-between;gap:8px}
.pane h2 span:last-child{text-transform:none;letter-spacing:0;color:var(--ink);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pane img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:6px;display:block}
.slidetext{margin-top:6px;font-size:12px;line-height:1.4;max-height:86px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.slidetext em{color:var(--muted);font-style:normal;display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.slidetext b{background:var(--ok);color:#fff;border-radius:3px;padding:0 2px;font-weight:600}
.neigh{display:flex;flex-direction:column;gap:6px}
.neigh div{border:2px solid var(--line);border-radius:6px;padding:4px;cursor:pointer;background:var(--bg)}
.neigh div:hover{border-color:var(--accent)} .neigh div.next{border-color:var(--ok)}
.neigh img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:4px;display:block}
.neigh span{font-size:11px;color:var(--muted);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.neigh div.next span{color:var(--ok);font-weight:600}
.caption{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:12px 0;min-height:48px}
.caption .now{background:var(--accent);color:#fff;border-radius:3px;padding:0 3px}
.caption .fut{color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:520px;overflow:auto}
.list h3{position:sticky;top:0;z-index:1;background:var(--card);margin:0;padding:8px 12px;font-size:13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:8px}
.row{padding:7px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:var(--bg)} .row.cur{box-shadow:inset 4px 0 var(--accent)}
.row.tr{border-left:4px solid var(--ok)} .row.note{border-left:4px solid var(--warn)} .row.flag{border-left-color:var(--bad)}
.row input.num{width:52px;padding:1px 4px;text-align:center}
.acts{float:right;display:inline-flex;gap:4px} .acts button{font-size:11px;padding:1px 7px}
.t{font-variant-numeric:tabular-nums;color:var(--muted)}
.why{color:var(--muted);font-size:12px}
.warn{color:var(--bad);font-size:12px}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px}
@media (max-width:860px){.stage,.cols{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap">
<header><h1 id="title"></h1><div class="tiles" id="tiles"></div></header>
<p class="guide">Listen, and press <b>Mark</b> the moment each transition should happen — the dropdown beside it says which.
If the wrong slide is showing, pick the right pair (or click a nearby slide). Notes can go in at any moment.
<kbd>space</kbd> play · <kbd>M</kbd> mark · <kbd>[</kbd> <kbd>]</kbd> change pair · <kbd>Esc</kbd> follow again · <kbd>N</kbd> note · <kbd>←</kbd> <kbd>→</kbd> 5 s</p>
<div class="controls">
  <audio id="audio" controls preload="auto"></audio>
  <button data-rate="1" class="on">1×</button><button data-rate="2">2×</button><button data-rate="4">4×</button>
</div>
<svg id="timeline" viewBox="0 0 1000 64" preserveAspectRatio="none"></svg>
<div class="legend"><i style="background:var(--accent)"></i>music<i style="background:#6a8fd8"></i>liturgist<i style="background:#d8a06a"></i>preacher<i style="background:#7bbf8a"></i>congregation · upper ticks: <span style="color:var(--ok)">your transitions</span>, <span style="color:var(--warn)">notes</span> · lower ticks: <span id="opLegend">operator</span> transitions</div>
<div class="marker">
  <button id="markBtn">Mark</button>
  <select id="pair" title="The transition the button records"></select>
  <span id="follow" class="pill auto"></span>
  <input id="noteText" placeholder="Note at this moment…  (Enter to add)">
  <button id="noteBtn">Add note</button>
  <span id="saveState"></span>
</div>
<div class="status"><span id="statusText"></span><span class="who" id="who"></span></div>
<div class="stage">
  <div class="pane"><h2><span id="onHead">On screen</span><span id="onLabel"></span></h2><img id="onImg" alt="Slide on screen"><div class="slidetext" id="onText"></div></div>
  <div class="pane"><h2><span>Next &amp; nearby</span><span id="nextLabel"></span></h2><div class="neigh" id="neigh"></div></div>
</div>
<div class="caption" id="caption"></div>
<div class="cols">
  <div class="list" id="marksList"><h3><span>Your marks · <span id="marksCount"></span></span><button id="copy">Copy</button></h3></div>
  <div class="list" id="opList"><h3><span id="opHead">Operator</span></h3></div>
</div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (id) => document.getElementById(id);
const audio = $('audio');
// Plain static servers ignore byte-range requests, which makes audio unseekable;
// a blob is seekable whatever the host does.
fetch(D.audio).then((r) => r.blob()).then((b) => { audio.src = URL.createObjectURL(b); })
  .catch(() => { audio.src = D.audio; });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
const bySlide = Object.fromEntries(D.slides.map((s) => [s.index, s]));
const order = D.slides.map((s) => s.index);
const after = (i) => { const k = order.indexOf(i); return k >= 0 && k < order.length - 1 ? order[k + 1] : null; };
const title = (i) => bySlide[i] ? (bySlide[i].title || (bySlide[i].cover ? '(blank)' : '')) : '';
const label = (i) => `${i} · ${title(i)}`;
const bisect = (a, t) => { let lo = 0, hi = a.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; };
const wordT = D.words.map((w) => w[0]);
const OP = D.operator, opMoves = OP ? OP.moves : [];
const TOL = 2.0;                                   // same as training/score.py
const round1 = (t) => Math.round(t * 10) / 10;

// Read fresh on every load; marksTag is the version this page holds, sent with
// every save so the server can refuse one made from a stale copy.
let marks = [], marksTag = null, loaded = false;
const sortMarks = () => marks.sort((a, b) => a.t - b.t);
const trans = () => marks.filter((m) => m.type === 'transition').sort((a, b) => a.t - b.t);
// Your marks are the deck: what they put on screen at time t.
function onScreenAt(t) { let s = D.first; for (const m of trans()) { if (m.t > t) break; s = m.to; } return s; }
// The pair the button records. It follows your marks unless set by hand, and a
// hand-set pair holds until you mark it or press Esc.
let manual = null;
const autoPair = (t) => { const f = onScreenAt(t); return { f, g: after(f) }; };
const pairAt = (t) => manual || autoPair(t);

const KEY = decodeURIComponent(location.pathname.split('/')[1]) || D.run;
$('title').innerHTML = `<a href="/">Services</a> / Marking · ${esc(KEY)} · <a href="../demo/">Demo</a>`;
document.title = `Marking · ${KEY}`;

// ---- saving ---------------------------------------------------------------
function setSave(text, err) { $('saveState').textContent = text; $('saveState').className = err ? 'err' : ''; }
let saving = Promise.resolve();
function save() { saving = saving.then(saveNow); return saving; }
async function saveNow() {
  sortMarks();
  const body = JSON.stringify(marks, null, 2);
  try {
    const r = await fetch(D.save, {method: 'PUT', headers: {'Content-Type': 'application/json', 'If-Match': marksTag}, body});
    if (r.status === 409 || r.status === 428) {
      loaded = false;
      throw new Error('the marks were changed elsewhere since this page opened; reload it');
    }
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    marksTag = r.headers.get('ETag');
    setSave(`saved · ${marks.length} marks`);
  } catch (err) {
    try { localStorage.setItem(`marks:${KEY}`, body); } catch (e) {}
    setSave(`NOT saved (${String(err.message || err).slice(0, 90)}) — Copy keeps them`, true);
  }
}
$('copy').onclick = async () => {
  const text = JSON.stringify(sortMarks(), null, 2);
  try { await navigator.clipboard.writeText(text); $('copy').textContent = 'Copied'; }
  catch (err) { window.prompt(`Copy these into runs/${KEY}/marks.json:`, text); }
  setTimeout(() => { $('copy').textContent = 'Copy'; }, 1500);
};

// ---- the pair dropdown ------------------------------------------------------
const sel = $('pair');
const pairText = (f, g) => `${f} → ${g}    ${title(f).slice(0, 26)} → ${title(g).slice(0, 26)}`;
for (const i of order) { const n = after(i); if (n != null) sel.add(new Option(pairText(i, n), `${i}:${n}`)); }
function ensureOption(f, g) {
  const v = `${f}:${g}`;
  if (![...sel.options].some((o) => o.value === v)) {
    const at = [...sel.options].findIndex((o) => +o.value.split(':')[0] > f);
    sel.add(new Option(pairText(f, g), v), at < 0 ? null : at);
  }
  return v;
}
function choose(p) {
  const a = autoPair(audio.currentTime);
  manual = (p.f === a.f && p.g === a.g) ? null : p;
  render();
}
sel.onchange = () => { const [f, g] = sel.value.split(':').map(Number); choose({f, g}); sel.blur(); };
function stepPair(d) {
  const opts = [...sel.options], k = opts.findIndex((o) => o.value === sel.value);
  const o = opts[Math.max(0, Math.min(opts.length - 1, k + d))];
  const [f, g] = o.value.split(':').map(Number); choose({f, g});
}

// ---- marking ----------------------------------------------------------------
function mark() {
  if (!loaded) return;
  const p = pairAt(audio.currentTime);
  if (p.g == null) return;
  marks.push({t: round1(audio.currentTime), type: 'transition', from: p.f, to: p.g});
  manual = null;
  const b = $('markBtn'); b.classList.add('flash'); setTimeout(() => b.classList.remove('flash'), 180);
  save(); renderAll();
}
function addNote() {
  const text = $('noteText').value.trim();
  if (!text || !loaded) return;
  marks.push({t: round1(audio.currentTime), type: 'note', text, slide: onScreenAt(audio.currentTime)});
  $('noteText').value = '';
  save(); renderAll();
}
$('markBtn').onclick = mark;
$('noteBtn').onclick = addNote;

// ---- timeline ---------------------------------------------------------------
let duration = (D.words.length ? D.words[D.words.length - 1][0] : 0) + 60;
const svg = $('timeline');
function drawTimeline() {
  const W = 1000, x = (t) => (t / duration) * W, r = (x0, y, w, h, c) => `<rect x="${x0}" y="${y}" width="${w}" height="${h}" style="fill:${c}"/>`;
  let h = r(0, 3, W, 15, 'var(--unk)');
  for (const [a, b] of D.music) h += r(x(a), 3, Math.max(1, x(b) - x(a)), 15, 'var(--accent)');
  const VC = {LITURGIST:'#6a8fd8', PREACHER:'#d8a06a', CONGREGATION:'#7bbf8a', OTHER:'var(--unk)'};
  for (const [a, b, role] of D.voices) h += r(x(a), 20, Math.max(1, x(b) - x(a)), 5, VC[role] || 'var(--unk)');
  for (const m of marks) h += m.type === 'transition' ? r(x(m.t), 28, 2, 14, 'var(--ok)') : r(x(m.t), 28, 1.6, 7, 'var(--warn)');
  for (const m of opMoves) h += r(x(m.t), 46, 1.4, 14, 'var(--muted)');
  svg.innerHTML = h + '<rect id="playhead" x="0" y="0" width="2.5" height="64" style="fill:var(--accent)"/>';
}
svg.addEventListener('click', (e) => { const b = svg.getBoundingClientRect(); seek(((e.clientX - b.left) / b.width) * duration); });
function seek(t) { audio.currentTime = Math.max(0, t); render(); }

// ---- the panes ----------------------------------------------------------------
const NORM = (w) => w.toLowerCase().replace(/[^a-z0-9]/g, '');
function paintText(id, slide, t) {
  const sl = bySlide[slide];
  if (!sl || !sl.text) { $(id).innerHTML = ''; return; }
  const i = bisect(wordT, t), heard = new Set();
  for (let k = Math.max(0, i - 25); k <= i; k++) if (D.words[k]) heard.add(NORM(D.words[k][1]));
  $(id).innerHTML = `<em>${esc(sl.src)}</em>` + sl.text.split(/\s+/).map((w) => {
    const n = NORM(w); return n.length > 2 && heard.has(n) ? `<b>${esc(w)}</b>` : esc(w); }).join(' ');
}
function renderNeigh(p) {
  const list = [];
  for (let k = p.g, n = 0; k != null && n < 3; k = after(k), n++) list.push(k);
  $('neigh').innerHTML = list.map((k, n) => `<div data-slide="${k}" class="${n === 0 ? 'next' : ''}" title="Mark ${p.f} → ${k}">`
    + `<img src="${bySlide[k].img}" alt=""><span>${n === 0 ? '→ ' : ''}${esc(label(k))}</span></div>`).join('');
  $('neigh').querySelectorAll('[data-slide]').forEach((d) => { d.onclick = () => choose({f: p.f, g: +d.dataset.slide}); });
}
let lastOn = null, lastKey = null;
function render() {
  const t = audio.currentTime, p = pairAt(t);
  if (p.g != null) sel.value = ensureOption(p.f, p.g);
  $('markBtn').textContent = p.g != null ? `Mark ${p.f} → ${p.g}` : 'End of deck';
  $('markBtn').disabled = p.g == null;
  const pill = $('follow');
  pill.textContent = manual ? 'set by hand — Mark it, or Esc to follow' : (audio.paused ? 'following your marks · paused' : 'following your marks');
  pill.className = 'pill ' + (manual ? 'manual' : 'auto');
  $('onHead').textContent = manual ? 'Marking from' : 'On screen';
  if (p.f !== lastOn) { $('onImg').src = bySlide[p.f].img; $('onLabel').textContent = label(p.f); lastOn = p.f; }
  paintText('onText', p.f, t);
  const key = `${p.f}:${p.g}`;
  if (key !== lastKey) { if (p.g != null) renderNeigh(p); else $('neigh').innerHTML = ''; $('nextLabel').textContent = p.g != null ? label(p.g) : ''; lastKey = key; }
  const ph = $('playhead'); if (ph) ph.setAttribute('x', (t / duration) * 1000 - 1);
  $('statusText').textContent = `${fmt(t)} · your marks have ${label(onScreenAt(t))} on screen`;
  const v = D.voices.find((x) => t >= x[0] && t < x[1]);
  $('who').textContent = v ? `${v[2]} · ${v[3]}` : 'silence';
  const wi = bisect(wordT, t), from = Math.max(0, wi - 14), to = Math.min(D.words.length, wi + 7);
  let cap = '';
  for (let k = from; k < to; k++) cap += `<span class="${k === wi ? 'now' : k > wi ? 'fut' : ''}">${esc(D.words[k][1])}</span> `;
  $('caption').innerHTML = `<span class="t">${fmt(t)}</span> &nbsp;${cap}`;
}

// ---- the lists ------------------------------------------------------------------
function nearestMark(slide, t) {
  let best = null;
  for (const u of trans()) if (u.to === slide && (!best || Math.abs(u.t - t) < Math.abs(best.t - t))) best = u;
  return best;
}
function renderMarks() {
  sortMarks();
  const host = $('marksList');
  host.querySelectorAll('.row').forEach((r) => r.remove());
  let shown = D.first;
  for (const m of marks) {
    const row = document.createElement('div');
    if (m.type === 'transition') {
      const off = m.from !== shown;
      row.className = 'row tr' + (off ? ' flag' : '');
      row.innerHTML = `<div><span class="t">${fmt(m.t)}</span> &nbsp;<input class="num" data-k="from" value="${m.from}"> → `
        + `<input class="num" data-k="to" value="${m.to}"> <span class="why">${esc(title(m.from).slice(0, 22))} → ${esc(title(m.to).slice(0, 22))}</span>`
        + `<span class="acts"><button data-a="play">▶</button><button data-a="del">✕</button></span></div>`
        + (off ? `<div class="warn">from ${m.from}, but your marks had ${shown} on screen here</div>` : '')
        + (m.text ? `<div class="why">“${esc(m.text)}”</div>` : '');
      shown = m.to;
      row.querySelectorAll('input.num').forEach((inp) => {
        inp.onclick = (e) => e.stopPropagation();
        inp.onchange = () => {
          const v = parseInt(inp.value, 10), other = inp.dataset.k === 'from' ? m.to : m.from;
          if (bySlide[v] && v !== other) { m[inp.dataset.k] = v; save(); }
          renderAll();
        };
      });
    } else {
      row.className = 'row note';
      row.innerHTML = `<div><span class="t">${fmt(m.t)}</span> &nbsp;<span class="pill note">note</span>`
        + (m.slide ? ` <span class="why">on ${m.slide}</span>` : '')
        + `<span class="acts"><button data-a="play">▶</button><button data-a="edit">edit</button><button data-a="del">✕</button></span></div>`
        + `<div>${esc(m.text)}</div>`;
      row.querySelector('[data-a="edit"]').onclick = (e) => {
        e.stopPropagation();
        const v = window.prompt('Note', m.text);
        if (v != null && v.trim()) { m.text = v.trim(); save(); renderAll(); }
      };
    }
    row.querySelector('[data-a="play"]').onclick = (e) => { e.stopPropagation(); seek(m.t - 5); audio.play(); };
    row.querySelector('[data-a="del"]').onclick = (e) => { e.stopPropagation(); marks = marks.filter((x) => x !== m); save(); renderAll(); };
    row.onclick = () => seek(m.t - 5);
    host.appendChild(row);
  }
  const n = trans().length;
  $('marksCount').textContent = `${n} transitions, ${marks.length - n} notes`;
}
function renderOp() {
  const host = $('opList');
  host.querySelectorAll('.row').forEach((r) => r.remove());
  if (!OP) {
    $('opHead').textContent = 'No operator has been replayed on this service';
    $('opLegend').textContent = 'operator'; return;
  }
  $('opHead').textContent = `${OP.name} — what it did` + (OP.foresight.length ? ' (uses foresight)' : '');
  $('opLegend').textContent = OP.name;
  for (const mv of opMoves) {
    const u = nearestMark(mv.to, mv.t), e = u ? mv.t - u.t : null;
    const pill = e === null ? '<span class="pill">not marked</span>'
      : Math.abs(e) <= TOL ? '<span class="pill ok">on time</span>'
      : `<span class="pill bad">${Math.abs(e).toFixed(1)}s ${e > 0 ? 'late' : 'early'}</span>`;
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<div><span class="t">${fmt(mv.t)}</span> &nbsp;${mv.from} → <b>${mv.to}</b> ${pill}</div><div class="why">${esc(mv.rule)}</div>`;
    row.onclick = () => seek(mv.t - 5);
    host.appendChild(row);
  }
}
function renderTiles() {
  const T = trans();
  let ok = 0, late = 0, early = 0, never = 0;
  for (const u of T) {
    const c = opMoves.filter((m) => m.to === u.to);
    if (!c.length) { never++; continue; }
    const n = c.reduce((a, b) => (Math.abs(b.t - u.t) < Math.abs(a.t - u.t) ? b : a));
    const e = n.t - u.t;
    if (Math.abs(e) <= TOL) ok++; else if (e > 0) late++; else early++;
  }
  const tiles = [['Transitions marked', T.length], ['Notes', marks.length - T.length]];
  if (OP && T.length) tiles.push([`${OP.name} on time`, `${ok}/${T.length}`], ['Late', late], ['Early', early], ['Never shown', never]);
  let html = tiles.map(([k, v]) => `<div class="tile"><b>${v}</b>${k}</div>`).join('');
  if (OP && OP.foresight.length) html += `<div class="tile warn" title="${esc(OP.foresight.join('; '))}"><b>not live-valid</b>${esc(OP.name)} used foresight</div>`;
  $('tiles').innerHTML = html;
}
function renderAll() { renderTiles(); renderMarks(); renderOp(); drawTimeline(); lastKey = null; render(); }

// ---- wiring ---------------------------------------------------------------------
audio.addEventListener('timeupdate', render);
audio.addEventListener('seeked', render);
audio.addEventListener('play', render);
audio.addEventListener('pause', render);
audio.addEventListener('loadedmetadata', () => { if (isFinite(audio.duration)) { duration = audio.duration; drawTimeline(); render(); } });
document.querySelectorAll('[data-rate]').forEach((b) => { b.onclick = () => { audio.playbackRate = +b.dataset.rate; document.querySelectorAll('[data-rate]').forEach((x) => x.classList.toggle('on', x === b)); }; });
document.addEventListener('keydown', (e) => {
  const tag = e.target.tagName;
  if (e.key === 'Escape') { manual = null; if (tag === 'INPUT' || tag === 'SELECT') e.target.blur(); render(); return; }
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
    if (e.target.id === 'noteText' && e.key === 'Enter') { e.preventDefault(); addNote(); }
    return;
  }
  if (e.target === audio || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = audio.currentTime;
  if (e.key === ' ') { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
  else if (e.key === 'ArrowLeft') seek(t - 5);
  else if (e.key === 'ArrowRight') seek(t + 5);
  else if (e.key === 'm' || e.key === 'M' || e.key === 'Enter') { e.preventDefault(); mark(); }
  else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); $('noteText').focus(); }
  else if (e.key === '[') stepPair(-1);
  else if (e.key === ']') stepPair(1);
});
renderAll();
fetch(D.save, {cache: 'no-store'}).then(async (r) => {
  if (!r.ok) throw new Error(`${r.status}`);
  marksTag = r.headers.get('ETag');
  marks = await r.json();
  loaded = true;
  setSave(marks.length ? `${marks.length} marks loaded` : 'no marks yet');
  renderAll();
}).catch((err) => setSave(`could not load the marks (${err.message}) — marking is off`, true));
</script>
</body></html>
'''


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
