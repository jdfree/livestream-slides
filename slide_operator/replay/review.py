"""Build a local review page for a replayed service.

    python -m slide_operator.replay.review runs/<date>
    python -m slide_operator.replay.serve 8791      # then open /<date>/review/

The page is for the person's evaluation, not the machine's. The reference is not
shown and not scored against: it has been wrong too often to arbitrate, and its
sung boundaries come from the same alignment the engine reads, so agreement with
it proves nothing.

Instead the page plays the service, shows the slide the engine had up, lists
every transition with the reason it fired, and lets the person record one
unambiguous fact — at THIS moment, THIS slide belongs on screen. Those marks are
the evaluation; they are written back to the run's verdicts.json, which
verdicts.py scores.
"""
from __future__ import annotations

import hashlib
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
    music = music_mod.analyze(run)
    dec = json.loads((run / "decisions.json").read_text())
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    vpath = run / "verdicts.json"
    marks = json.loads(vpath.read_text()) if vpath.exists() else []
    vspath = run / "voices.json"
    voices = json.loads(vspath.read_text())["segments"] if vspath.exists() else []
    data = {
        "run": run.name,
        "build": hashlib.sha1(
            (json.dumps(dec["moves"]) + str(len(slides))).encode()).hexdigest()[:8],
        "audio": "../audio.webm",
        "save": "../verdicts.json",
        "first": slides[0].index,
        "slides": [{"index": s.index, "title": s.title, "img": f"slides/{s.index:03d}.png",
                    # what the system believes is on the slide: OCR of the sheet
                    # music, or the slide's own body text
                    "text": (s.lyrics or s.body).replace("\n", " ")[:400],
                    "src": "sheet-music OCR" if s.lyrics else "slide text"}
                   for s in slides],
        "moves": dec["moves"],
        "marks": marks,
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
<title>Slide review</title>
<style>
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e0e0da;--ok:#2f9e5b;--bad:#d64545;--warn:#c98a2f;--unk:#c9c9c2;--accent:#3b6fd6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecece8;--muted:#9a9a94;--line:#34342f;--unk:#4a4a45}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,system-ui,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
h1{font-size:18px;margin:0}
.tiles{display:flex;gap:8px;flex-wrap:wrap}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;color:var(--muted);font-size:12px}
.tile b{display:block;font-size:18px;color:var(--ink)}
.guide{color:var(--muted);margin:10px 0}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
audio{flex:1;min-width:240px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 10px;cursor:pointer}
button.on{border-color:var(--accent);color:var(--accent)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
input,select{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 8px}
#timeline{width:100%;height:64px;display:block;margin-top:10px;cursor:pointer;background:var(--card);border:1px solid var(--line);border-radius:8px}
.legend{color:var(--muted);font-size:12px;margin:4px 0 12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
.status{font-weight:600;margin-bottom:8px}
.who{display:inline-block;margin-left:10px;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:var(--card);color:var(--muted)}
#saveState{float:right;font-weight:400;font-size:12px;color:var(--muted)}
.stage{display:grid;grid-template-columns:2fr 1fr;gap:12px}
.pane{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;min-width:0}
.pane h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 6px;display:flex;justify-content:space-between;gap:8px}
.pane h2 span:last-child{text-transform:none;letter-spacing:0;color:var(--ink);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pane img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:6px;display:block}
.slidetext{margin-top:6px;font-size:12px;line-height:1.4;max-height:86px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.slidetext em{color:var(--muted);font-style:normal;display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.slidetext b{background:var(--ok);color:#fff;border-radius:3px;padding:0 2px;font-weight:600}
.neigh{display:flex;flex-direction:column;gap:6px}
.neigh div{border:1px solid var(--line);border-radius:6px;padding:4px;cursor:pointer;background:var(--bg)}
.neigh div:hover{border-color:var(--accent)}
.neigh img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:4px;display:block}
.neigh span{font-size:11px;color:var(--muted);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.marker{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:12px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.marker b{font-variant-numeric:tabular-nums}
.caption{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:12px 0;min-height:48px}
.caption .now{background:var(--accent);color:#fff;border-radius:3px;padding:0 3px}
.caption .fut{color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:480px;overflow:auto}
.list h3{position:sticky;top:0;z-index:1;background:var(--card);margin:0;padding:8px 12px;font-size:13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:8px}
.row{padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:var(--bg)} .row.cur{box-shadow:inset 4px 0 var(--accent)}
.row.judged{border-left:4px solid var(--ok)}
.row.flagged{border-left:4px solid var(--bad)}
.t{font-variant-numeric:tabular-nums;color:var(--muted)}
.why{color:var(--muted);font-size:12px}
.acts{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.acts button{font-size:12px;padding:2px 8px}
.pill{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.pill.ok{color:var(--ok);border-color:var(--ok)} .pill.bad{color:var(--bad);border-color:var(--bad)} .pill.legacy{color:var(--warn);border-color:var(--warn)}
@media (max-width:860px){.stage,.cols{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap">
<header><h1 id="title"></h1><div class="tiles" id="tiles"></div></header>
<p class="guide">Your marks are the evaluation. Play the service; when the slide on screen is wrong, scrub to the moment it
<em>should</em> have changed, pick the slide, and press <b>Mark</b>. A transition you approve just needs <b>Right</b>.
Keys: <b>space</b> play/pause · <b>← →</b> 5 s · <b>N</b>/<b>P</b> next/previous transition · <b>M</b> mark here.</p>
<div class="controls">
  <audio id="audio" controls preload="auto"></audio>
  <button data-rate="1" class="on">1×</button><button data-rate="2">2×</button><button data-rate="4">4×</button>
</div>
<svg id="timeline" viewBox="0 0 1000 64" preserveAspectRatio="none"></svg>
<div class="legend"><i style="background:var(--accent)"></i>music playing<i style="background:#6a8fd8"></i>liturgist<i style="background:#d8a06a"></i>preacher<i style="background:#7bbf8a"></i>congregation · upper ticks: engine transitions · lower ticks: your marks</div>
<div class="status" id="status"><span id="statusText"></span><span class="who" id="who"></span><span id="saveState"></span></div>
<div class="stage">
  <div class="pane"><h2><span>On screen</span><span id="engineLabel"></span></h2><img id="engineImg" alt="Slide the engine displayed"><div class="slidetext" id="engineText"></div></div>
  <div class="pane"><h2><span>Nearby slides</span><span></span></h2><div class="neigh" id="neigh"></div></div>
</div>
<div class="marker">
  <span>At <b id="markT">0:00</b> the right slide is</span>
  <select id="markSlide"></select>
  <input id="markNote" placeholder="note (optional)" size="34">
  <button id="markAdd" class="primary">Mark</button>
  <span class="why" id="markHint"></span>
</div>
<div class="caption" id="caption"></div>
<div class="cols">
  <div class="list" id="moves"><h3><span>Engine transitions · <span id="movesCount"></span></span></h3></div>
  <div class="list" id="marks"><h3><span>Your marks · <span id="marksCount"></span></span><button id="copy">Copy</button></h3></div>
</div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (id) => document.getElementById(id);
const audio = $('audio');
// Plain static servers ignore byte-range requests, which makes audio unseekable.
// Loading the file as a blob makes every position seekable regardless of server.
fetch(D.audio).then((r) => r.blob()).then((b) => { audio.src = URL.createObjectURL(b); })
  .catch(() => { audio.src = D.audio; });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const fmt1 = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
const bySlide = Object.fromEntries(D.slides.map((s) => [s.index, s]));
const bisect = (a, t) => { let lo = 0, hi = a.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; };
const moveT = D.moves.map((m) => m.t), wordT = D.words.map((w) => w[0]);
const engineAt = (t) => { const i = bisect(moveT, t); return i < 0 ? D.first : D.moves[i].to; };
const label = (i) => `${i} · ${bySlide[i] ? bySlide[i].title : ''}`;
const TOL = 2.0;                       // matches verdicts.py
let marks = D.marks.slice();

$('title').textContent = `Slide review · ${D.run}`;

// ---- marks -----------------------------------------------------------------
// One unambiguous fact per mark: at time t, slide to_slide belongs on screen.
// Older files may carry too_early/too_late, whose t meant different things in
// different entries; those are shown as legacy for you to re-confirm, never
// silently graded.
const LEGACY = (m) => m.kind === 'too_early' || m.kind === 'too_late';
const nearestMoveTo = (slide, t) => {
  let best = null;
  for (const m of D.moves) if (m.to === slide && (!best || Math.abs(m.t - t) < Math.abs(best.t - t))) best = m;
  return best;
};
const markOk = (mk) => {
  if (LEGACY(mk)) return null;
  const n = nearestMoveTo(mk.to_slide, mk.t);
  return n ? Math.abs(n.t - mk.t) <= TOL : false;
};

let saveState = '';
function setSave(text) { saveState = text; $('saveState').textContent = text; }
async function save() {
  const body = JSON.stringify(marks, null, 2);
  try {
    const r = await fetch(D.save, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body});
    if (!r.ok) throw new Error(r.status);
    setSave(`saved to verdicts.json · ${marks.length}`);
  } catch (err) {
    try { localStorage.setItem(`marks:${D.run}`, body); } catch (e) {}
    setSave('saved in this browser only — press Copy (server is read-only)');
  }
}

function tiles() {
  const judged = new Set();
  for (const mk of marks) { const n = nearestMoveTo(mk.to_slide, mk.t); if (n && Math.abs(n.t - mk.t) <= 20) judged.add(n.t); }
  const ok = marks.filter((m) => markOk(m) === true).length;
  const bad = marks.filter((m) => markOk(m) === false).length;
  const legacy = marks.filter(LEGACY).length;
  $('tiles').innerHTML = [['Marks', marks.length], ['Engine agrees', ok], ['Engine off', bad],
                          ['Needs re-check', legacy], ['Transitions', D.moves.length]]
    .map(([k, v]) => `<div class="tile"><b>${v}</b>${k}</div>`).join('');
  $('marksCount').textContent = `${marks.length}`;
  $('movesCount').textContent = `${D.moves.length}`;
}

function addMark(t, slide, note, kind) {
  marks.push({t: Math.round(t * 10) / 10, to_slide: slide, note: note || '', kind: kind || 'exact'});
  marks.sort((a, b) => a.t - b.t);
  save(); renderMarks(); tiles(); drawTimeline(); renderMoves();
}

function renderMarks() {
  const host = $('marks');
  host.querySelectorAll('.row').forEach((r) => r.remove());
  for (const mk of marks) {
    const ok = markOk(mk);
    const n = nearestMoveTo(mk.to_slide, mk.t);
    const row = document.createElement('div');
    row.className = 'row' + (ok === true ? ' judged' : ok === false ? ' flagged' : '');
    const pill = LEGACY(mk) ? '<span class="pill legacy">re-check</span>'
      : ok ? '<span class="pill ok">engine agrees</span>' : '<span class="pill bad">engine off</span>';
    const got = n ? `engine went at ${fmt1(n.t)} (${(n.t - mk.t >= 0 ? '+' : '')}${(n.t - mk.t).toFixed(1)}s)` : 'engine never showed it';
    row.innerHTML = `<div><span class="t">${fmt1(mk.t)}</span> &nbsp;show <b>${esc(label(mk.to_slide))}</b> ${pill}</div>
      <div class="why">${esc(got)}</div>${mk.note ? `<div class="why">“${esc(mk.note)}”</div>` : ''}
      <div class="acts"><button data-act="go">Play</button><button data-act="del">Delete</button></div>`;
    row.querySelector('[data-act="go"]').onclick = (e) => { e.stopPropagation(); seek(mk.t - 6); audio.play(); };
    row.querySelector('[data-act="del"]').onclick = (e) => {
      e.stopPropagation(); marks = marks.filter((x) => x !== mk); save(); renderMarks(); tiles(); drawTimeline(); renderMoves();
    };
    row.onclick = () => { seek(mk.t - 6); };
    host.appendChild(row);
  }
}

function renderMoves() {
  const host = $('moves');
  host.querySelectorAll('.row').forEach((r) => r.remove());
  D.moves.forEach((m) => {
    const mine = marks.find((mk) => Math.abs(mk.t - m.t) <= TOL && mk.to_slide === m.to);
    const row = document.createElement('div');
    row.className = 'row' + (mine ? ' judged' : '');
    row.innerHTML = `<div><span class="t">${fmt1(m.t)}</span> &nbsp;${m.from} → <b>${esc(label(m.to))}</b>
        ${mine ? '<span class="pill ok">you marked this right</span>' : ''}</div>
      <div class="why">${esc(m.rule)}</div><div class="why">heard: “${esc(m.heard)}”</div>
      <div class="acts"><button data-act="ok">Right</button><button data-act="fix">Wrong — mark the real moment</button></div>`;
    row.querySelector('[data-act="ok"]').onclick = (e) => {
      e.stopPropagation(); addMark(m.t, m.to, `confirmed: ${m.rule}`, 'good');
    };
    row.querySelector('[data-act="fix"]').onclick = (e) => {
      e.stopPropagation(); seek(m.t - 10); $('markSlide').value = String(m.to);
      $('markHint').textContent = `scrub to when slide ${m.to} really belongs, then press Mark`;
      audio.play();
    };
    row.onclick = () => { seek(m.t - 8); audio.play(); };
    host.appendChild(row);
  });
}

// ---- timeline --------------------------------------------------------------
let duration = (D.words.length ? D.words[D.words.length - 1][0] : 0) + 60;
const svg = $('timeline');
function drawTimeline() {
  const W = 1000, x = (t) => (t / duration) * W, r = (x0, y, w, h, c) => `<rect x="${x0}" y="${y}" width="${w}" height="${h}" style="fill:${c}"/>`;
  let h = r(0, 4, W, 18, 'var(--unk)');
  for (const [a, b] of D.music) h += r(x(a), 4, Math.max(1, x(b) - x(a)), 18, 'var(--accent)');
  const VC = {LITURGIST:'#6a8fd8', PREACHER:'#d8a06a', CONGREGATION:'#7bbf8a', OTHER:'var(--unk)'};
  for (const [a, b, role] of D.voices) h += r(x(a), 24, Math.max(1, x(b) - x(a)), 6, VC[role] || 'var(--unk)');
  for (const m of D.moves) h += r(x(m.t), 33, 1.4, 11, 'var(--ink)');
  for (const mk of marks) {
    const ok = markOk(mk);
    h += r(x(mk.t), 47, 2, 14, ok === true ? 'var(--ok)' : ok === false ? 'var(--bad)' : 'var(--warn)');
  }
  svg.innerHTML = h + '<rect id="playhead" x="0" y="0" width="2.5" height="64" style="fill:var(--accent)"/>';
}
svg.addEventListener('click', (e) => { const b = svg.getBoundingClientRect(); seek(((e.clientX - b.left) / b.width) * duration); });
audio.addEventListener('loadedmetadata', () => { if (isFinite(audio.duration)) { duration = audio.duration; drawTimeline(); update(); } });

function seek(t) { audio.currentTime = Math.max(0, t); update(); }

// Show what the system believes the slide says, and mark the words it has just
// heard — so a mismatch between slide text and audio is visible, not inferred.
const NORM = (w) => w.toLowerCase().replace(/[^a-z0-9]/g, '');
function paintText(id, slide, t) {
  const sl = bySlide[slide];
  if (!sl || !sl.text) { $(id).innerHTML = ''; return; }
  const i = bisect(wordT, t);
  const heard = new Set();
  for (let k = Math.max(0, i - 25); k <= i; k++) if (D.words[k]) heard.add(NORM(D.words[k][1]));
  const marked = sl.text.split(/\s+/).map((w) => {
    const n = NORM(w);
    return n.length > 2 && heard.has(n) ? `<b>${esc(w)}</b>` : esc(w);
  }).join(' ');
  $(id).innerHTML = `<em>${esc(sl.src)}</em>${marked}`;
}

let lastEngine = null;
function update() {
  const t = audio.currentTime;
  const ph = $('playhead'); if (ph) ph.setAttribute('x', (t / duration) * 1000 - 1);
  const e = engineAt(t);
  $('statusText').textContent = `${fmt1(t)} · on screen: ${label(e)}`;
  const v = D.voices.find((x) => t >= x[0] && t < x[1]);
  $('who').textContent = v ? `${v[2]} · ${v[3]}` : 'silence';
  $('markT').textContent = fmt1(t);
  if (e !== lastEngine) {
    $('engineImg').src = bySlide[e].img; $('engineLabel').textContent = label(e);
    const n = [];
    for (let k = e - 1; k <= e + 2; k++) if (bySlide[k] && k !== e) n.push(k);
    $('neigh').innerHTML = n.map((k) => `<div data-slide="${k}"><img src="${bySlide[k].img}" alt=""><span>${esc(label(k))}</span></div>`).join('');
    $('neigh').querySelectorAll('[data-slide]').forEach((d) => {
      d.onclick = () => { $('markSlide').value = d.dataset.slide; $('markHint').textContent = `slide ${d.dataset.slide} selected — press Mark`; };
    });
    if (!document.activeElement || document.activeElement.id !== 'markSlide') $('markSlide').value = String(e);
    lastEngine = e;
  }
  paintText('engineText', e, t);
  const wi = bisect(wordT, t), from = Math.max(0, wi - 14), to = Math.min(D.words.length, wi + 7);
  let cap = '';
  for (let k = from; k < to; k++) cap += `<span class="${k === wi ? 'now' : k > wi ? 'fut' : ''}">${esc(D.words[k][1])}</span> `;
  $('caption').innerHTML = `<span class="t">${fmt1(t)}</span> &nbsp;${cap}`;
  const mi = bisect(moveT, t);
  document.querySelectorAll('#moves .row').forEach((row, k) => row.classList.toggle('cur', k === mi));
}
audio.addEventListener('timeupdate', update);
audio.addEventListener('seeked', update);

$('markSlide').innerHTML = D.slides.map((s) => `<option value="${s.index}">${esc(label(s.index)).slice(0, 60)}</option>`).join('');
$('markAdd').onclick = () => {
  addMark(audio.currentTime, +$('markSlide').value, $('markNote').value.trim(), 'exact');
  $('markNote').value = ''; $('markHint').textContent = 'marked';
};
$('copy').onclick = async () => {
  const text = JSON.stringify(marks, null, 2);
  try { await navigator.clipboard.writeText(text); $('copy').textContent = 'Copied'; }
  catch (err) { window.prompt('Copy these marks into runs/' + D.run + '/verdicts.json:', text); }
  setTimeout(() => { $('copy').textContent = 'Copy'; }, 1500);
};

document.querySelectorAll('[data-rate]').forEach((b) => { b.onclick = () => { audio.playbackRate = +b.dataset.rate; document.querySelectorAll('[data-rate]').forEach((x) => x.classList.toggle('on', x === b)); }; });

document.addEventListener('keydown', (e) => {
  if (e.target === audio || e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.metaKey || e.ctrlKey) return;
  const t = audio.currentTime;
  if (e.key === ' ') { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
  else if (e.key === 'ArrowLeft') seek(t - 5);
  else if (e.key === 'ArrowRight') seek(t + 5);
  else if (e.key === 'n' || e.key === 'N') { const m = D.moves.find((m) => m.t > t + 0.2); if (m) seek(m.t - 6); }
  else if (e.key === 'p' || e.key === 'P') { const m = [...D.moves].reverse().find((m) => m.t < t - 6.5); if (m) seek(m.t - 6); }
  else if (e.key === 'm' || e.key === 'M') { $('markAdd').click(); }
});

setSave('');
tiles(); renderMarks(); renderMoves(); drawTimeline(); update();
</script>
</body></html>
'''


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
