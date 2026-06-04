from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backlog import Backlog
from dispatch import loop_status
from lease import LeaseTable


def build_state(root) -> dict:
    root = Path(root)
    return {
        "tasks": Backlog(root).list(),
        "leases": LeaseTable(root).active(),
        "loop": loop_status(root),
    }


def handle_path(root, path) -> tuple[int, str, bytes]:
    path = path.split("?", 1)[0]
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8")
    if path == "/api/state":
        body = json.dumps(build_state(root), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", body
    return 404, "text/plain; charset=utf-8", b"not found"


def serve(root, host: str = "127.0.0.1", port: int = 8787) -> None:
    root = Path(root)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, ctype, body = handle_path(root, self.path)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep console quiet
            pass

    httpd = HTTPServer((host, port), Handler)
    print(f"cwo dashboard on http://{host}:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>cwo dashboard</title>
<style>
  body{font:14px/1.5 system-ui,sans-serif;margin:24px;color:#222}
  h1{font-size:18px} h2{font-size:13px;text-transform:uppercase;color:#666;margin:0 0 8px}
  .muted{color:#888}
  .cols{display:flex;gap:16px;flex-wrap:wrap}
  .col{flex:1;min-width:200px;background:#f6f6f6;border-radius:8px;padding:12px}
  .task{background:#fff;border:1px solid #e2e2e2;border-radius:6px;padding:8px;margin-bottom:8px}
  .task .id{font-weight:600} .task .meta{color:#888;font-size:12px}
  table{border-collapse:collapse;width:100%;margin-top:8px}
  td,th{border:1px solid #e2e2e2;padding:4px 8px;text-align:left;font-size:13px}
  .pill{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;background:#e2e2e2}
</style>
</head>
<body>
<h1>cwo dashboard <span class="muted" id="ts"></span></h1>
<div id="loop"></div>
<div class="cols" id="cols"></div>
<h2>Active leases</h2>
<div id="leases"></div>
<script>
const STATUSES=["inbox","ready","active","done"];
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
async function tick(){
  let s; try{ s=await (await fetch("/api/state")).json(); }catch(e){ return; }
  const by={}; STATUSES.forEach(x=>by[x]=[]);
  s.tasks.forEach(t=>{(by[t.status]||(by[t.status]=[])).push(t);});
  document.getElementById("cols").innerHTML=STATUSES.map(st=>`
    <div class="col"><h2>${st} (${by[st].length})</h2>
    ${by[st].map(t=>`<div class="task"><span class="id">${esc(t.id)}</span> ${esc(t.title)}
      <div class="meta">touches=${esc(JSON.stringify(t.touches))}${t.depends_on.length?(" deps="+esc(JSON.stringify(t.depends_on))):""}${t.auto?' <span class="pill">auto</span>':''}</div></div>`).join("")}
    </div>`).join("");
  const lp=s.loop;
  document.getElementById("loop").innerHTML=`<p class="muted">counts: ${esc(JSON.stringify(lp.counts))} ·
    dispatchable: ${esc(JSON.stringify(lp.dispatchable))} · blocked: ${esc(JSON.stringify(lp.blocked_auto.map(b=>b.id)))} ·
    needs_approval: ${esc(JSON.stringify(lp.needs_approval))} · loop_can_progress: <b>${lp.loop_can_progress}</b></p>`;
  document.getElementById("leases").innerHTML = s.leases.length? `<table><tr><th>task</th><th>touches</th><th>worktree</th><th>heartbeat</th></tr>
    ${s.leases.map(l=>`<tr><td>${esc(l.task)}</td><td>${esc(JSON.stringify(l.touches))}</td><td>${esc(l.worktree||"")}</td><td>${esc(l.heartbeat||"")}</td></tr>`).join("")}</table>`
    : '<p class="muted">none</p>';
  document.getElementById("ts").textContent="· updated "+new Date().toLocaleTimeString();
}
tick(); setInterval(tick,3000);
</script>
</body>
</html>
"""
