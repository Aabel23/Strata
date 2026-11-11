"""Disposable feasibility spike for agent cards linked to a live Strata PTY.

Run ``python3 design/agent-session-spike.py`` and open the printed local URL.
This does not start Claude/Codex or modify the Strata server. The demo button
runs harmless processes with Claude/Codex argv names to test discovery.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strata.term import TerminalManager  # noqa: E402

PAGE = r"""<!doctype html><html lang="vi"><meta charset="utf-8">
<title>Agent session spike</title><link rel="stylesheet" href="/vendor/xterm.css"><style>
*{box-sizing:border-box}body{margin:0;background:#121116;color:#e9e3d8;font:14px system-ui}
.layout{height:100vh;display:grid;grid-template-columns:minmax(0,1fr) 320px;grid-template-rows:minmax(0,3fr) minmax(180px,2fr)}
main{padding:22px;border-right:1px solid #37313c}aside{grid-row:1/3;grid-column:2;padding:18px;border-left:1px solid #37313c;background:#19171e}
#agents{grid-column:1;grid-row:2;border-top:3px solid #765e50;padding:14px 20px;overflow:auto}
h1,h2{margin:0 0 12px;color:#d9ae82}p{color:#a9a3ab;line-height:1.5}
button{background:#2a2530;color:#f4e9dc;border:1px solid #66535d;border-radius:7px;padding:8px 12px;cursor:pointer}
#cards{display:flex;align-items:flex-start;gap:16px;min-height:100px;overflow-x:auto;padding:5px 0 14px}
.card{min-width:225px;max-width:260px;text-align:left;padding:12px;line-height:1.65;background:#211c25;border-color:#866a58}
.card small{color:#aaa2aa}.child{margin-left:22px;position:relative}.child:before{content:'└──';position:absolute;left:-32px;color:#d9ae82}
.dot{color:#80cbb0}.terminal{height:55vh;overflow:hidden;background:#09090c;padding:12px}
#chatout{height:58vh}dialog{width:min(850px,90vw);border:1px solid #856956;background:#19171e;color:#eee;border-radius:10px}
dialog::backdrop{background:#000a}.bar{display:flex;justify-content:space-between;align-items:center;gap:12px}
</style><div class="layout"><main><h1>Board / Task</h1><p>Spike tách biệt: phần trên mô phỏng vùng làm việc. Không gọi mô hình.</p></main>
<aside><h2>AI chat cũ · Terminal</h2><button id="demo">Chạy session giả lập</button>
<p>Claude và subagent Codex giả lập chạy trong hai PTY riêng. Thẻ xuất hiện tự động ở dưới.</p>
<div class="terminal" id="chatout"></div></aside>
<section id="agents"><h2>Agents <span id="count">0</span></h2><div id="cards"></div></section></div>
<dialog id="popup"><div class="bar"><h2 id="title"></h2><button id="close">Đóng</button></div>
<p id="meta"></p><div class="terminal" id="popupout"></div></dialog>
<script src="/vendor/xterm.js"></script><script>
const token=new URLSearchParams(location.search).get('token');
const headers={'X-Spike-Token':token};
let primaryId=null,selectedTerm=null,popupTerm=null;
const offsets={},histories={};
const termOptions={fontFamily:'monospace',fontSize:13,theme:{background:'#09090c',foreground:'#e9e3d8'}};
const chatTerm=new Terminal(termOptions);chatTerm.open(document.getElementById('chatout'));
chatTerm.onData(data=>api('/api/terminal/input',{data}));
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{...headers,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error(await r.text());return r.json()}
function render(rows){document.getElementById('count').textContent=rows.length;const box=document.getElementById('cards');box.replaceChildren();
  for(const s of rows){const b=document.createElement('button');b.className='card'+(s.parent?' child':'');
    const title=document.createElement('strong');title.textContent='● '+s.kind+' · đang chạy';title.className='dot';
    const info=document.createElement('div');info.textContent='Task: —';
    const branch=document.createElement('div');branch.textContent='Branch: '+(s.branch||'—');
    const pid=document.createElement('small');pid.textContent='PID '+s.pid+' · terminal '+s.terminal;
    b.append(title,info,branch,pid);b.onclick=()=>{document.getElementById('title').textContent=s.kind+' · PID '+s.pid;
      document.getElementById('meta').textContent='Branch: '+(s.branch||'—')+' · CWD: '+s.cwd;
      selectedTerm=s.terminal;document.getElementById('popup').showModal();if(popupTerm)popupTerm.dispose();
      popupTerm=new Terminal(termOptions);popupTerm.open(document.getElementById('popupout'));
      popupTerm.write(histories[selectedTerm]||'');popupTerm.onData(data=>api('/api/terminal/input',{terminal:selectedTerm,data}));popupTerm.focus()};box.append(b)}
}
async function readTerm(id){const r=await api('/api/terminal/read?terminal='+encodeURIComponent(id)+'&after='+(offsets[id]||0));offsets[id]=r.next;
  if(r.data){const bytes=Uint8Array.from(atob(r.data),c=>c.charCodeAt(0));const chunk=new TextDecoder().decode(bytes);
    histories[id]=((histories[id]||'')+chunk).slice(-16000);
    if(id===primaryId)chatTerm.write(bytes);if(id===selectedTerm&&popupTerm)popupTerm.write(bytes)}}
async function poll(){try{const data=await api('/api/sessions');primaryId=data.primary;render(data.sessions);
  for(const id of new Set([primaryId,...data.sessions.map(s=>s.terminal)]))await readTerm(id)}
  catch(e){document.getElementById('count').textContent='!'}}
document.getElementById('demo').onclick=()=>api('/api/demo',{});
document.getElementById('close').onclick=()=>{document.getElementById('popup').close();popupTerm.dispose();popupTerm=null;selectedTerm=null};
poll();setInterval(poll,700);
</script></html>"""


def proc_info(pid: int) -> dict | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        tail = stat[stat.rfind(")") + 2:].split()
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        cwd = os.readlink(f"/proc/{pid}/cwd")
        return {"pid": pid, "ppid": int(tail[1]), "start": int(tail[19]),
                "argv0": os.path.basename(os.fsdecode(cmd[0])) if cmd and cmd[0] else "", "cwd": cwd}
    except (OSError, ValueError, IndexError):
        return None


def branch_for(cwd: str) -> str | None:
    try:
        p = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=cwd,
                           capture_output=True, text=True, timeout=1, check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def discover(term_pid: int, term_id: str) -> list[dict]:
    procs = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            info = proc_info(int(entry.name))
            if info:
                procs[info["pid"]] = info
    descendants = {term_pid}
    changed = True
    while changed:
        old = len(descendants)
        descendants.update(p["pid"] for p in procs.values() if p["ppid"] in descendants)
        changed = len(descendants) != old
    found = []
    for pid in descendants:
        p = procs.get(pid)
        if not p or p["argv0"] not in {"claude", "codex"}:
            continue
        parent = p["ppid"] if procs.get(p["ppid"], {}).get("argv0") in {"claude", "codex"} else None
        found.append({"id": f"{pid}:{p['start']}", "pid": pid, "kind": p["argv0"].title(),
                      "parent": parent, "branch": branch_for(p["cwd"]), "cwd": p["cwd"], "terminal": term_id})
    return sorted(found, key=lambda p: (bool(p["parent"]), p["pid"]))


def make_handler(manager: TerminalManager, term_id: str, token: str, cwd: str):
    state = {"child": None}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: bytes, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, value: dict):
            self._send(200, json.dumps(value).encode())

        def _allowed(self) -> bool:
            return self.headers.get("X-Spike-Token") == token

        def _term(self, requested: str | None):
            selected = requested or term_id
            if selected not in {term_id, state["child"]}:
                raise KeyError("unknown terminal")
            return manager.get(selected)

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/" and parse_qs(u.query).get("token") == [token]:
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                return
            if u.path in {"/vendor/xterm.js", "/vendor/xterm.css"}:
                source = ROOT / "viewer" / u.path.lstrip("/")
                self._send(200, source.read_bytes(), "text/javascript" if u.path.endswith(".js") else "text/css")
                return
            if not self._allowed():
                self._send(403, b"forbidden", "text/plain")
                return
            requested = parse_qs(u.query).get("terminal", [None])[0]
            try:
                t = self._term(requested)
            except KeyError:
                self._send(404, b"terminal missing", "text/plain")
                return
            if u.path == "/api/sessions":
                primary = discover(manager.get(term_id)._proc.pid, term_id)
                child = discover(manager.get(state["child"])._proc.pid, state["child"]) if state["child"] else []
                for session in child:
                    session["parent"] = primary[0]["pid"] if primary else None
                self._json({"primary": term_id, "sessions": primary + child})
            elif u.path == "/api/terminal/read":
                after = int(parse_qs(u.query).get("after", ["0"])[0])
                data, next_offset, closed = t.read(after, wait=0)
                self._json({"data": base64.b64encode(data).decode(), "next": next_offset, "closed": closed})
            else:
                self._send(404, b"missing", "text/plain")

        def do_POST(self):
            if not self._allowed():
                self._send(403, b"forbidden", "text/plain")
                return
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 4096)))
            except (ValueError, TypeError):
                self._send(400, b"bad request", "text/plain")
                return
            try:
                t = self._term(body.get("terminal"))
            except KeyError:
                self._send(404, b"terminal missing", "text/plain")
                return
            if self.path == "/api/demo":
                if state["child"] is None:
                    child = manager.open(cwd, title="subagent")
                    state["child"] = child.id
                t.write(b"bash -c 'exec -a claude sleep 90'\n")
                manager.get(state["child"]).write(b"bash -c 'exec -a codex sleep 90'\n")
            elif self.path == "/api/terminal/input" and isinstance(body.get("data"), str):
                t.write(body["data"].encode())
            else:
                self._send(404, b"missing", "text/plain")
                return
            self._json({"ok": True})

        def log_message(self, *_):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    manager = TerminalManager()
    term = manager.open(args.cwd, title="spike")
    token = secrets.token_urlsafe(18)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(manager, term.id, token, args.cwd))
    print(f"http://127.0.0.1:{server.server_port}/?token={token}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close_all()


if __name__ == "__main__":
    main()
