"""The local pages around the harness: the list of services, and the intake form
for a new one. Served by replay/serve.py; the ingest itself runs in a background
thread there, one at a time."""
from __future__ import annotations

import html
import json
import threading
import time
import uuid
from pathlib import Path

from . import ingest

JOBS: dict[str, dict] = {}
_lock = threading.Lock()

STYLE = """
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e0e0da;--accent:#3b6fd6;--ok:#2f9e5b;--bad:#d64545;--warn:#c98a2f}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecece8;--muted:#9a9a94;--line:#34342f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,system-ui,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:32px 20px}
h1{font-size:22px;margin:0 0 6px} h1 a{color:var(--muted);text-decoration:none;font-weight:400}
p{color:var(--muted)}
a.card{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:10px 0}
a.card:hover{border-color:var(--accent)}
.meta{color:var(--muted);font-size:13px}
.right{float:right;font-size:13px;font-variant-numeric:tabular-nums}
.btn{display:inline-block;background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 16px;font:inherit;text-decoration:none;cursor:pointer}
label{display:block;font-weight:600;margin:14px 0 4px}
label small{font-weight:400;color:var(--muted)}
input{width:100%;font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:8px 10px}
.steps{list-style:none;padding:0;margin:16px 0}
.steps li{padding:3px 0;color:var(--muted)} .steps li.now{color:var(--ink);font-weight:600} .steps li.done{color:var(--ok)}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;max-height:320px;overflow:auto;font-size:12px;white-space:pre-wrap}
.err{color:var(--bad);font-weight:600}
"""


def index_page(runs: Path) -> str:
    cards = []
    for d in sorted((p for p in runs.iterdir() if (p / "deck.pptx").exists()), reverse=True):
        b = json.loads((d / "bundle.json").read_text()) if (d / "bundle.json").exists() else {}
        marks = json.loads((d / "marks.json").read_text()) if (d / "marks.json").exists() else []
        nt = sum(1 for m in marks if m.get("type") == "transition")
        ready = (d / "review" / "index.html").exists()
        right = f"{nt} transitions · {len(marks) - nt} notes" if marks else "not yet marked"
        href = f"/{d.name}/review/" if ready else f"/{d.name}/"
        cards.append(f'<a class="card" href="{href}"><span class="right">{right}</span><b>{d.name}</b>'
                     f'<div class="meta">{html.escape(b.get("title") or "")}'
                     f'{"" if ready else " · harness not built"}</div></a>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Services · marking</title>
<style>{STYLE}</style></head><body><div class="wrap">
<h1>Services</h1>
<p>Each service is a bundle: the recording, the slides, the bulletin, and your marks. Open one to mark its transitions.</p>
<p><a class="btn" href="/intake/">+ New service</a></p>
{''.join(cards) or '<p>No services yet.</p>'}
<p class="meta">Published read-only at <a href="https://jdfree.github.io/livestream-slides/">jdfree.github.io/livestream-slides</a></p>
</div></body></html>"""


def intake_page() -> str:
    steps = "".join(f'<li data-step="{k}">{html.escape(v)}</li>' for k, v in ingest.STEPS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>New service</title>
<style>{STYLE}</style></head><body><div class="wrap">
<h1><a href="/">Services</a> / New service</h1>
<p>Builds a bundle for a new service and opens it in the marking harness. Takes several minutes:
the recording is transcribed and the sheet music read.</p>
<form id="f">
<label>YouTube recording <small>— watch, live or studio link</small></label>
<input name="youtube" required placeholder="https://www.youtube.com/watch?v=…">
<label>Slides <small>— a path on this computer, or a link that downloads the .pptx</small></label>
<input name="slides" required placeholder="~/Downloads/092026 PowerPoint.pptx">
<label>Bulletin <small>— a path or download link to the .pdf (or .docx)</small></label>
<input name="bulletin" required placeholder="~/Downloads/St Peter September 20 Bulletin.pdf">
<label>Service date <small>— optional; taken from the video if blank</small></label>
<input name="date" placeholder="YYYY-MM-DD">
<p><button class="btn" type="submit">Build the bundle</button></p>
</form>
<div id="job" hidden><ul class="steps" id="steps">{steps}</ul><div id="msg"></div><pre id="log"></pre></div>
<script>
const f = document.getElementById('f');
f.onsubmit = async (e) => {{
  e.preventDefault();
  const body = Object.fromEntries(new FormData(f).entries());
  const r = await fetch('/api/ingest', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}});
  const j = await r.json();
  if (!r.ok) {{ document.getElementById('job').hidden = false; document.getElementById('msg').innerHTML = `<p class="err">${{j.error}}</p>`; return; }}
  f.querySelector('button').disabled = true;
  document.getElementById('job').hidden = false;
  poll(j.job);
}};
async function poll(id) {{
  const j = await (await fetch(`/api/jobs/${{id}}`)).json();
  let seen = true;
  document.querySelectorAll('#steps li').forEach((li) => {{
    const now = li.dataset.step === j.step;
    if (now) seen = false;
    li.className = now && j.state === 'running' ? 'now' : (seen || j.state === 'done') ? 'done' : '';
  }});
  document.getElementById('log').textContent = j.log.join('\\n');
  document.getElementById('log').scrollTop = 1e9;
  const msg = document.getElementById('msg');
  if (j.state === 'done') msg.innerHTML = `<p><a class="btn" href="/${{j.run}}/review/">Open the marking harness →</a></p>`;
  else if (j.state === 'failed') msg.innerHTML = `<p class="err">Failed: ${{j.error}}</p>`;
  else {{ msg.textContent = `${{j.elapsed}}s elapsed…`; setTimeout(() => poll(id), 2000); }}
}}
</script></div></body></html>"""


def start(req: dict) -> tuple[int, dict]:
    missing = [k for k in ("youtube", "slides", "bulletin") if not str(req.get(k, "")).strip()]
    if missing:
        return 400, {"error": f"missing: {', '.join(missing)}"}
    try:
        ingest.video_id(req["youtube"])
    except ValueError as e:
        return 400, {"error": str(e)}
    with _lock:
        if any(j["state"] == "running" for j in JOBS.values()):
            return 409, {"error": "a service is already being built; wait for it to finish"}
        jid = uuid.uuid4().hex[:10]
        job = JOBS[jid] = {"state": "running", "step": None, "run": None, "error": None,
                           "log": [], "started": time.time()}

    def log(line):
        job["log"] = (job["log"] + [line])[-400:]

    def work():
        try:
            run = ingest.build(req["youtube"], req["slides"], req["bulletin"],
                               (req.get("date") or "").strip() or None,
                               log=log, step=lambda s: job.update(step=s))
            job.update(state="done", run=run.name)
        except Exception as e:  # reported to the page, not raised into the server
            job.update(state="failed", error=f"{type(e).__name__}: {e}")
            log(job["error"])

    threading.Thread(target=work, daemon=True).start()
    return 202, {"job": jid}


def status(jid: str) -> tuple[int, dict]:
    j = JOBS.get(jid)
    if not j:
        return 404, {"error": "no such job"}
    return 200, {**{k: v for k, v in j.items() if k != "started"},
                 "elapsed": int(time.time() - j["started"])}
