from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backlog import Backlog
from dispatch import dispatch, dispatch_auto, loop_status
from integrate import integrate
from cwo_gc import gc
from lease import LeaseTable
from lock import project_lock


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


def handle_post(root, path, body: bytes) -> tuple[int, str, bytes]:
    ct = "application/json; charset=utf-8"
    path = path.split("?", 1)[0]
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return 400, ct, b'{"error": "invalid json"}'
    routes = {"/api/add", "/api/classify", "/api/dispatch",
              "/api/dispatch-auto", "/api/integrate", "/api/gc"}
    if path not in routes:
        return 404, ct, b'{"error": "not found"}'
    try:
        with project_lock(root):
            if path == "/api/add":
                tid = Backlog(root).add(
                    data["title"], type=data.get("type", "feature"),
                    source=data.get("source", "human"),
                    priority=data.get("priority", "medium"))
                result = {"id": tid}
            elif path == "/api/classify":
                Backlog(root).classify(
                    data["id"], touches=data.get("touches", []),
                    depends_on=data.get("depends_on", []),
                    auto=bool(data.get("auto", False)))
                result = {"ok": True, "id": data["id"]}
            elif path == "/api/dispatch":
                result = {"ok": True, "worktree": str(dispatch(root, data["id"]))}
            elif path == "/api/dispatch-auto":
                result = {"dispatched": dispatch_auto(root)}
            elif path == "/api/integrate":
                result = integrate(root, data["id"])
            else:  # /api/gc
                result = {"reclaimed": gc(root)}
    except Exception as e:
        return 400, ct, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
    return 200, ct, json.dumps(result, ensure_ascii=False).encode("utf-8")


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

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            status, ctype, resp = handle_post(root, self.path, body)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

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
  .task .actions{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center}
  .task .actions input[type=text]{font-size:12px;padding:2px 4px;border:1px solid #ccc;border-radius:4px;width:120px}
  .task .actions label{font-size:12px;color:#666}
  table{border-collapse:collapse;width:100%;margin-top:8px}
  td,th{border:1px solid #e2e2e2;padding:4px 8px;text-align:left;font-size:13px}
  .pill{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;background:#e2e2e2}
  .toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px;padding:10px 12px;background:#f0f0f0;border-radius:8px}
  .toolbar input[type=text]{font-size:13px;padding:4px 8px;border:1px solid #ccc;border-radius:4px;min-width:200px}
  button{font-size:12px;padding:3px 10px;border:1px solid #bbb;border-radius:4px;background:#fff;cursor:pointer}
  button:hover{background:#e8e8e8}
</style>
</head>
<body>
<h1>cwo dashboard <span class="muted" id="ts"></span></h1>
<div class="toolbar">
  <input type="text" id="add-title" placeholder="task title">
  <select id="add-type" style="font-size:13px;padding:4px;border:1px solid #ccc;border-radius:4px">
    <option value="feature">feature</option>
    <option value="bug">bug</option>
    <option value="chore">chore</option>
  </select>
  <button onclick="addTask()">+ add task</button>
  <button onclick="postJSON('/api/dispatch-auto', {}).then(r=>r.error?alert(r.error):alert('dispatched: '+JSON.stringify(r.dispatched)))">dispatch-auto</button>
  <button onclick="postJSON('/api/gc', {}).then(r=>r.error?alert(r.error):alert('gc reclaimed: '+JSON.stringify(r.reclaimed)))">gc</button>
</div>
<div id="loop"></div>
<div class="cols" id="cols"></div>
<h2>Active leases</h2>
<div id="leases"></div>
<script>
const STATUSES=["inbox","ready","active","done"];
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

async function postJSON(path, obj){
  let r;
  try{
    r=await (await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj)})).json();
  }catch(e){alert("network error: "+e); return {};}
  if(r.error){alert("error: "+r.error);}
  tick();
  return r;
}

async function addTask(){
  const title=document.getElementById("add-title").value.trim();
  if(!title){alert("title required");return;}
  const type=document.getElementById("add-type").value;
  const r=await postJSON("/api/add",{title,type});
  if(!r.error){document.getElementById("add-title").value="";}
}

function classifyTask(id, inputId, checkId){
  const raw=document.getElementById(inputId).value.trim();
  const touches=raw?raw.split(/[ \t]+/):[];
  const auto=document.getElementById(checkId).checked;
  postJSON("/api/classify",{id,touches,auto});
}

function dispatchTask(id){
  postJSON("/api/dispatch",{id}).then(r=>{if(!r.error)alert("dispatched: "+r.worktree);});
}

function integrateTask(id){
  postJSON("/api/integrate",{id}).then(r=>{if(!r.error)alert("integrated: "+JSON.stringify(r));});
}

async function tick(){
  let s; try{ s=await (await fetch("/api/state")).json(); }catch(e){ return; }
  const by={}; STATUSES.forEach(x=>by[x]=[]);
  s.tasks.forEach(t=>{(by[t.status]||(by[t.status]=[])).push(t);});
  document.getElementById("cols").innerHTML=STATUSES.map(st=>`
    <div class="col"><h2>${st} (${by[st].length})</h2>
    ${by[st].map(t=>{
      const inputId="ti-"+t.id; const checkId="tc-"+t.id;
      let actions="";
      if(st==="ready"){
        actions=`<div class="actions">
          <input type="text" id="${esc(inputId)}" placeholder="touches (space-sep)" value="${esc((t.touches||[]).join(" "))}">
          <label><input type="checkbox" id="${esc(checkId)}"${t.auto?" checked":""}> auto</label>
          <button onclick="classifyTask('${esc(t.id)}','${esc(inputId)}','${esc(checkId)}')">classify</button>
          <button onclick="dispatchTask('${esc(t.id)}')">dispatch</button>
        </div>`;
      } else if(st==="active"){
        actions=`<div class="actions"><button onclick="integrateTask('${esc(t.id)}')">integrate</button></div>`;
      }
      return `<div class="task"><span class="id">${esc(t.id)}</span> ${esc(t.title)}
        <div class="meta">touches=${esc(JSON.stringify(t.touches))}${t.depends_on.length?(" deps="+esc(JSON.stringify(t.depends_on))):""}${t.auto?' <span class="pill">auto</span>':''}</div>${actions}</div>`;
    }).join("")}
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
