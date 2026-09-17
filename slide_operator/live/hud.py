"""The operator's heads-up display.

A person standing by the keyboard has to be able to answer, at a glance: what is
on screen, what is coming, what the system just heard, why it last moved, and
whether it is currently holding back because someone took over. All of that is
here, refreshed four times a second.

Served over plain HTTP with polling — no dependencies, and nothing to install on
the booth machine.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Hud:
    def __init__(self, slides_dir: Path, port: int = 8792):
        self.slides_dir, self.port = slides_dir, port
        self._state: dict = {}
        self._lock = threading.Lock()
        self._server = None

    def publish(self, state: dict) -> None:
        with self._lock:
            self._state = state

    def start(self) -> str:
        hud = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):        # keep the console for the operator
                pass

            def do_GET(self):
                if self.path.startswith("/state"):
                    with hud._lock:
                        body = json.dumps(hud._state).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/slides/"):
                    p = hud.slides_dir / Path(self.path).name
                    if not p.exists():
                        self.send_error(404); return
                    data = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    body = PAGE.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://localhost:{self.port}/"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Slide operator</title>
<style>
:root{--bg:#12120f;--card:#1c1c19;--ink:#f2f2ec;--muted:#9a9a90;--line:#33332d;
      --ok:#4fb477;--warn:#e0a43b;--bad:#d8564f;--accent:#6a8fd8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:14px}
header{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
h1{font-size:16px;margin:0;letter-spacing:.02em}
.pill{padding:3px 12px;border-radius:999px;border:1px solid var(--line);background:var(--card);font-size:13px;color:var(--muted)}
.pill b{color:var(--ink)}
.pill.live{border-color:var(--ok);color:var(--ok)}
.pill.hold{border-color:var(--bad);color:var(--bad)}
.pill.music{border-color:var(--accent);color:var(--accent)}
.grid{display:grid;grid-template-columns:1.25fr 1.25fr 1fr;gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.card h2{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
         display:flex;justify-content:space-between;gap:8px}
.card h2 span:last-child{text-transform:none;letter-spacing:0;color:var(--ink)}
.card.now{border-color:var(--ok)} .card.now.held{border-color:var(--bad)}
img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:7px;display:block}
.txt{margin-top:8px;font-size:12.5px;color:var(--muted);max-height:74px;overflow:auto}
.heard{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:12px;min-height:44px}
.heard span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;display:block;margin-bottom:3px}
.rows{max-height:320px;overflow:auto}
.row{padding:7px 2px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:0}
.t{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:6px}
.why{color:var(--muted);font-size:12px}
.iv{color:var(--warn)}
.meter{height:6px;background:#000;border-radius:3px;overflow:hidden;margin-top:8px}
.meter i{display:block;height:100%;background:var(--ok)}
@media (max-width:1100px){.grid{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<header>
  <h1>SLIDE OPERATOR</h1>
  <span class="pill" id="clock">--:--</span>
  <span class="pill" id="deck">deck --</span>
  <span class="pill" id="voice">-</span>
  <span class="pill" id="musicPill">silence</span>
  <span class="pill" id="state">starting</span>
</header>
<div class="grid">
  <div class="card now" id="nowCard"><h2><span>On screen</span><span id="nowLabel"></span></h2>
    <img id="nowImg" alt=""><div class="txt" id="nowText"></div>
    <div class="meter"><i id="level" style="width:0%"></i></div></div>
  <div class="card"><h2><span>Next</span><span id="nextLabel"></span></h2>
    <img id="nextImg" alt=""><div class="txt" id="nextText"></div></div>
  <div class="card"><h2><span>Decisions</span><span id="guards"></span></h2>
    <div class="rows" id="log"></div></div>
</div>
<div class="heard"><span>Heard just now</span><div id="heard"></div></div>
</div>
<script>
const $ = (id) => document.getElementById(id);
const fmt = (t) => `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let lastNow = null, lastNext = null;

async function poll() {
  try {
    const s = await (await fetch('/state', {cache:'no-store'})).json();
    if (s && s.slide) render(s);
  } catch (e) {}
  setTimeout(poll, 250);
}
function card(pfx, c, lastKey) {
  if (!c) { $(pfx+'Label').textContent = '—'; return lastKey; }
  const key = c.index;
  if (key !== lastKey) {
    $(pfx+'Img').src = '/slides/' + String(c.index).padStart(3,'0') + '.png';
    $(pfx+'Text').textContent = c.text || '';
  }
  const tags = [c.sung ? 'sung' : '', c.cover ? 'cover' : ''].filter(Boolean).join(' · ');
  $(pfx+'Label').textContent = `${c.index} · ${c.title}${tags ? '  (' + tags + ')' : ''}`;
  return key;
}
function render(s) {
  $('clock').innerHTML = `<b>${fmt(s.t)}</b>`;
  $('deck').innerHTML = `deck <b>${s.actual ?? '—'}</b> / ${s.total}` + (s.presenting ? '' : ' · not presenting');
  $('voice').textContent = s.voice || '-';
  const mp = $('musicPill');
  mp.textContent = s.music ? 'music' : 'silence';
  mp.className = 'pill' + (s.music ? ' music' : '');
  const st = $('state');
  st.textContent = s.holding ? `HOLDING ${s.hold_left}s — a person moved back` : 'operating';
  st.className = 'pill ' + (s.holding ? 'hold' : 'live');
  $('nowCard').className = 'card now' + (s.holding ? ' held' : '');
  lastNow = card('now', s.slide, lastNow);
  lastNext = card('next', s.next, lastNext);
  $('level').style.width = Math.max(0, Math.min(100, (s.level_db + 60) / 60 * 100)) + '%';
  $('heard').textContent = s.heard || '—';
  $('guards').textContent = `dwell ${s.guards.MIN_DWELL}s · hold ${s.guards.MANUAL_HOLD}s`;
  const rows = [];
  for (const iv of (s.interventions || []))
    rows.push(`<div class="row iv"><span class="t">${fmt(iv.t)}</span>${esc(iv.event.replace('_',' '))}: ${iv.from} → ${iv.to}</div>`);
  for (const d of (s.decisions || []))
    rows.push(`<div class="row"><span class="t">${fmt(d.t)}</span>${d.from} → <b>${d.to}</b><div class="why">${esc(d.rule)}</div></div>`);
  $('log').innerHTML = rows.join('') || '<div class="row why">no decisions yet</div>';
}
poll();
</script></body></html>
'''
