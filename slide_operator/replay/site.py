"""Build the static showcase site for GitHub Pages.

    python -m slide_operator.replay.site runs/2026-09-13 docs

The same service the review harness shows, as a page that can be served from
anywhere: the audio, the timeline, the slide the engine had on screen, what it
believed that slide said, every decision and its reason, and the human record it
is graded against.

It is read-only by construction — a static host has nothing to write back to — so
the marking controls are gone. Everything else the harness does is here.

The score is computed here, by the same verdicts.py the command line uses, so the
published numbers cannot drift from the real scorer.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ..ingest import deck as deck_mod, melody
from . import verdicts as verdicts_mod


def build(run: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    slides = deck_mod.load(run / "deck.pptx")
    melody.attach(slides, run / "deck.pptx", run / "lyrics.json")
    dec = json.loads((run / "decisions.json").read_text())
    moves = dec["moves"]
    words = [json.loads(l) for l in open(run / "words.jsonl")]
    music = json.loads((run / "music.json").read_text())
    vpath = run / "voices.json"
    voices = json.loads(vpath.read_text())["segments"] if vpath.exists() else []

    first = slides[0].index
    res = verdicts_mod.score(run, moves, first)
    marks = [{"t": r["want"], "to": r["to"], "note": r["note"],
              "error": r["error"], "ok": r["ok"]} for r in res["rows"]]

    # Slide images are copied by the caller or here if they are not already there.
    src = run / "review" / "slides"
    dst = out / "slides"
    dst.mkdir(exist_ok=True)
    for png in sorted(src.glob("*.png")):
        if not (dst / png.name).exists():
            shutil.copy2(png, dst / png.name)

    data = {
        "run": run.name,
        "audio": "audio.webm",
        "first": first,
        "slides": [{"index": s.index, "title": s.title, "img": f"slides/{s.index:03d}.png",
                    "text": (s.lyrics or s.body).replace("\n", " ")[:400],
                    "src": "sheet-music OCR" if s.lyrics else "slide text"}
                   for s in slides],
        "moves": moves,
        "marks": sorted(marks, key=lambda m: m["t"]),
        "score": {"correct": res["correct"], "checked": res["checked"],
                  "late": res["late"], "early": res["early"], "never": res["never"]},
        "music": [[r["t0"], r["t1"]] for r in music["regions"]],
        "voices": [[v["t0"], v["t1"], v["role"], v["mode"]] for v in voices],
        "words": [[w["start"], w["w"]] for w in words],
    }
    payload = json.dumps(data).replace("</", "<\\/")
    page = out / "index.html"
    page.write_text(PAGE.replace("__DATA__", payload))
    (out / ".nojekyll").write_text("")
    return page


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Slide operator · September 13</title>
<style>
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e0e0da;--ok:#2f9e5b;--bad:#d64545;--unk:#c9c9c2;--accent:#3b6fd6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecece8;--muted:#9a9a94;--line:#34342f;--unk:#4a4a45}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,system-ui,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;justify-content:space-between}
h1{font-size:19px;margin:0}
.sub{color:var(--muted);margin:4px 0 0;max-width:62ch}
.tiles{display:flex;gap:8px;flex-wrap:wrap}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;color:var(--muted);font-size:12px}
.tile b{display:block;font-size:18px;color:var(--ink)}
.guide{color:var(--muted);margin:10px 0}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
audio{flex:1;min-width:240px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 10px;cursor:pointer}
button.on{border-color:var(--accent);color:var(--accent)}
#timeline{width:100%;height:64px;display:block;margin-top:10px;cursor:pointer;background:var(--card);border:1px solid var(--line);border-radius:8px}
.legend{color:var(--muted);font-size:12px;margin:4px 0 12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
.status{font-weight:600;margin-bottom:8px}
.who{display:inline-block;margin-left:10px;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:var(--card);color:var(--muted)}
.stage{display:grid;grid-template-columns:2fr 1fr;gap:12px}
.pane{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;min-width:0}
.pane h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 6px;display:flex;justify-content:space-between;gap:8px}
.pane h2 span:last-child{text-transform:none;letter-spacing:0;color:var(--ink);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pane img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:6px;display:block}
.slidetext{margin-top:6px;font-size:12px;line-height:1.4;max-height:86px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.slidetext em{color:var(--muted);font-style:normal;display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.slidetext b{background:var(--ok);color:#fff;border-radius:3px;padding:0 2px;font-weight:600}
.neigh{display:flex;flex-direction:column;gap:6px}
.neigh div{border:1px solid var(--line);border-radius:6px;padding:4px;background:var(--bg)}
.neigh img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:4px;display:block}
.neigh span{font-size:11px;color:var(--muted);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.caption{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:12px 0;min-height:48px}
.caption .now{background:var(--accent);color:#fff;border-radius:3px;padding:0 3px}
.caption .fut{color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:480px;overflow:auto}
.list h3{position:sticky;top:0;z-index:1;background:var(--card);margin:0;padding:8px 12px;font-size:13px;border-bottom:1px solid var(--line)}
.row{padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:var(--bg)} .row.cur{box-shadow:inset 4px 0 var(--accent)}
.row.ok{border-left:4px solid var(--ok)} .row.bad{border-left:4px solid var(--bad)}
.t{font-variant-numeric:tabular-nums;color:var(--muted)}
.why{color:var(--muted);font-size:12px}
.pill{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.pill.ok{color:var(--ok);border-color:var(--ok)} .pill.bad{color:var(--bad);border-color:var(--bad)}
footer{color:var(--muted);font-size:12px;margin:20px 0 8px}
@media (max-width:860px){.stage,.cols{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap">
<header>
  <div><h1 id="title"></h1>
  <p class="sub">An AI slide operator following a church service: it reads the deck and the worship folder
  beforehand, then listens — aligning each slide's own printed words to the audio and matching the printed
  notes to the tune — and decides when to advance. Play the service and watch what it did.</p></div>
  <div class="tiles" id="tiles"></div>
</header>
<p class="guide">Click the timeline or any decision to jump there. <b>space</b> play/pause · <b>← →</b> 5 s · <b>N</b>/<b>P</b> next/previous transition.</p>
<div class="controls">
  <audio id="audio" controls preload="none"></audio>
  <button data-rate="1" class="on">1×</button><button data-rate="2">2×</button><button data-rate="4">4×</button>
</div>
<svg id="timeline" viewBox="0 0 1000 64" preserveAspectRatio="none"></svg>
<div class="legend"><i style="background:var(--accent)"></i>music playing<i style="background:#6a8fd8"></i>liturgist<i style="background:#d8a06a"></i>preacher<i style="background:#7bbf8a"></i>congregation · upper ticks: transitions · lower ticks: human marks (<span style="color:var(--ok)">met</span> / <span style="color:var(--bad)">missed</span>)</div>
<div class="status" id="status"><span id="statusText"></span><span class="who" id="who"></span></div>
<div class="stage">
  <div class="pane"><h2><span>On screen</span><span id="engineLabel"></span></h2><img id="engineImg" alt="Slide on screen"><div class="slidetext" id="engineText"></div></div>
  <div class="pane"><h2><span>Nearby slides</span><span></span></h2><div class="neigh" id="neigh"></div></div>
</div>
<div class="caption" id="caption"></div>
<div class="cols">
  <div class="list" id="moves"><h3>Transitions · <span id="movesCount"></span></h3></div>
  <div class="list" id="marks"><h3>Human record · <span id="marksCount"></span></h3></div>
</div>
<footer id="foot"></footer>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (id) => document.getElementById(id);
const audio = $('audio');
// Fetched as a blob rather than pointed straight at the file: a static host that
// ignores byte-range requests leaves the audio unseekable, and a review page you
// cannot scrub is useless. One download buys seeking on any host.
fetch(D.audio).then((r) => r.blob()).then((b) => { audio.src = URL.createObjectURL(b); })
  .catch(() => { audio.src = D.audio; });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
const bySlide = Object.fromEntries(D.slides.map((s) => [s.index, s]));
const bisect = (a, t) => { let lo = 0, hi = a.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; };
const moveT = D.moves.map((m) => m.t), wordT = D.words.map((w) => w[0]);
const engineAt = (t) => { const i = bisect(moveT, t); return i < 0 ? D.first : D.moves[i].to; };
const label = (i) => `${i} · ${bySlide[i] ? bySlide[i].title : ''}`;

$('title').textContent = `Slide operator · ${D.run}`;
const S = D.score;
$('tiles').innerHTML = [['Human marks met', `${S.correct}/${S.checked}`], ['Late', S.late], ['Early', S.early],
                        ['Never shown', S.never], ['Transitions', D.moves.length]]
  .map(([k, v]) => `<div class="tile"><b>${v}</b>${k}</div>`).join('');
$('movesCount').textContent = D.moves.length;
$('marksCount').textContent = `${S.correct} of ${S.checked} met`;
$('foot').innerHTML = `Graded only against the human record — what a person watching the service said belonged on screen. `
  + `Audio re-encoded to 32&nbsp;kbps mono for the web.`;

let duration = (D.words.length ? D.words[D.words.length - 1][0] : 0) + 60;
const svg = $('timeline');
function drawTimeline() {
  const W = 1000, x = (t) => (t / duration) * W, r = (x0, y, w, h, c) => `<rect x="${x0}" y="${y}" width="${w}" height="${h}" style="fill:${c}"/>`;
  let h = r(0, 4, W, 18, 'var(--unk)');
  for (const [a, b] of D.music) h += r(x(a), 4, Math.max(1, x(b) - x(a)), 18, 'var(--accent)');
  const VC = {LITURGIST:'#6a8fd8', PREACHER:'#d8a06a', CONGREGATION:'#7bbf8a', OTHER:'var(--unk)'};
  for (const [a, b, role] of D.voices) h += r(x(a), 24, Math.max(1, x(b) - x(a)), 6, VC[role] || 'var(--unk)');
  for (const m of D.moves) h += r(x(m.t), 33, 1.4, 11, 'var(--ink)');
  for (const mk of D.marks) h += r(x(mk.t), 47, 2, 14, mk.ok ? 'var(--ok)' : 'var(--bad)');
  svg.innerHTML = h + '<rect id="playhead" x="0" y="0" width="2.5" height="64" style="fill:var(--accent)"/>';
}
svg.addEventListener('click', (e) => { const b = svg.getBoundingClientRect(); seek(((e.clientX - b.left) / b.width) * duration); });
audio.addEventListener('loadedmetadata', () => { if (isFinite(audio.duration)) { duration = audio.duration; drawTimeline(); update(); } });
function seek(t) { audio.currentTime = Math.max(0, t); update(); }

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
  $('statusText').textContent = `${fmt(t)} · on screen: ${label(e)}`;
  const v = D.voices.find((x) => t >= x[0] && t < x[1]);
  $('who').textContent = v ? `${v[2]} · ${v[3]}` : 'silence';
  if (e !== lastEngine) {
    $('engineImg').src = bySlide[e].img; $('engineLabel').textContent = label(e);
    const n = [];
    for (let k = e - 1; k <= e + 2; k++) if (bySlide[k] && k !== e) n.push(k);
    $('neigh').innerHTML = n.map((k) => `<div><img src="${bySlide[k].img}" alt=""><span>${esc(label(k))}</span></div>`).join('');
    lastEngine = e;
  }
  paintText('engineText', e, t);
  const wi = bisect(wordT, t), from = Math.max(0, wi - 14), to = Math.min(D.words.length, wi + 7);
  let cap = '';
  for (let k = from; k < to; k++) cap += `<span class="${k === wi ? 'now' : k > wi ? 'fut' : ''}">${esc(D.words[k][1])}</span> `;
  $('caption').innerHTML = `<span class="t">${fmt(t)}</span> &nbsp;${cap}`;
  const mi = bisect(moveT, t);
  document.querySelectorAll('#moves .row').forEach((row, k) => row.classList.toggle('cur', k === mi));
}
audio.addEventListener('timeupdate', update);
audio.addEventListener('seeked', update);

for (const m of D.moves) {
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<div><span class="t">${fmt(m.t)}</span> &nbsp;${m.from} → <b>${esc(label(m.to))}</b></div>
    <div class="why">${esc(m.rule)}</div><div class="why">heard: “${esc(m.heard)}”</div>`;
  row.onclick = () => { seek(m.t - 8); audio.play(); };
  $('moves').appendChild(row);
}
for (const mk of D.marks) {
  const row = document.createElement('div');
  row.className = 'row ' + (mk.ok ? 'ok' : 'bad');
  const err = mk.error === null ? 'never shown'
    : mk.error === 0 ? 'on screen'
    : `${mk.error > 0 ? '+' : ''}${mk.error.toFixed(1)}s ${mk.error > 0 ? 'late' : 'early'}`;
  row.innerHTML = `<div><span class="t">${fmt(mk.t)}</span> &nbsp;show <b>${esc(label(mk.to))}</b>
      <span class="pill ${mk.ok ? 'ok' : 'bad'}">${esc(err)}</span></div>
    <div class="why">“${esc(mk.note)}”</div>`;
  row.onclick = () => { seek(mk.t - 6); audio.play(); };
  $('marks').appendChild(row);
}

document.querySelectorAll('[data-rate]').forEach((b) => { b.onclick = () => { audio.playbackRate = +b.dataset.rate; document.querySelectorAll('[data-rate]').forEach((x) => x.classList.toggle('on', x === b)); }; });
document.addEventListener('keydown', (e) => {
  if (e.target === audio || e.metaKey || e.ctrlKey) return;
  const t = audio.currentTime;
  if (e.key === ' ') { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
  else if (e.key === 'ArrowLeft') seek(t - 5);
  else if (e.key === 'ArrowRight') seek(t + 5);
  else if (e.key === 'n' || e.key === 'N') { const m = D.moves.find((m) => m.t > t + 0.2); if (m) seek(m.t - 6); }
  else if (e.key === 'p' || e.key === 'P') { const m = [...D.moves].reverse().find((m) => m.t < t - 6.5); if (m) seek(m.t - 6); }
});
drawTimeline(); update();
</script>
</body></html>
'''


if __name__ == "__main__":
    run = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs")
    print(build(run, out))
