"""MCP server over stdio (JSON-RPC 2.0, one JSON message per line). Role is fixed at launch; clients cannot pass one."""
import json, pathlib, sys, traceback
from strata import blocks, c4_layered, db, service

CAP, MAX_LINE = 8000, 1 << 20
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
ALL, MAIN, WORK = ("main", "coder", "reviewer"), ("main",), ("main", "coder")
S = lambda d="": {"type": "string", "description": d}
I = lambda d="": {"type": "integer", "description": d}
def schema(props, req): return {"type": "object", "properties": props, "required": req}
STATUS = {"type": "string", "enum": ["proposed", "approved", "open", "doing", "review", "done", "rejected"]}


def _get_item(c, role, id):
    i = service.get_item(c, id)
    i["links"] = [r[0] for r in c.execute("SELECT object_id FROM c4_link WHERE project=? AND ref_kind='item' AND ref_id=? ORDER BY object_id", (i["project"], id))]
    i["audit"] = [dict(r) for r in c.execute("SELECT ts,actor_role,tool,after FROM audit WHERE target=? ORDER BY id DESC LIMIT 5", (f"item:{id}",))]
    body = i.pop("body")  # last and as real lines, so the cap can cut a long body at a line boundary
    return json.dumps(i, ensure_ascii=False, indent=1) + (f"\n--- body ---\n{body}" if body else "")


def _list_items(c, role, project=None, kind=None, status=None, owner=None, ready=False, limit=50, label=None):
    return service.list_items(c, project, kind, status, owner, ready, label)[:max(1, limit)]


def _get_doc(c, role, project, path):
    r = c.execute("SELECT docs_dir FROM project WHERE id=?", (project,)).fetchone()
    if not r or not r["docs_dir"] or not path.endswith(".yaml") or any(x.startswith(".") for x in path.split("/")): raise KeyError(f"no doc {project}/{path}")
    root = pathlib.Path(r["docs_dir"]).resolve(); f = (root / path).resolve()
    if not (f.is_relative_to(root) and f.is_file()): raise KeyError(f"no doc {project}/{path}")
    d, errs = blocks.load_doc(f.read_text(encoding="utf-8", errors="replace"))
    return {**d, "errors": errs}


def _audit(c, role, project, limit=20):
    return [dict(r) for r in c.execute("SELECT id,ts,actor_role,tool,target,before,after FROM audit WHERE project=? ORDER BY id DESC LIMIT ?", (project, limit))]


def _context(c, role, id, budget=12000):
    from strata import context
    return context.build(c, id, budget)


def _move(to):
    def f(c, role, id, note=None, actor=None):
        service.transition(c, role, id, to, actor, note)
        return {"ok": True, "status": to}
    return f


def _approve(c, role, id, note=None, actor=None):
    cur = c.execute("SELECT status FROM item WHERE id=?", (id,)).fetchone()
    if not cur: raise KeyError(f"no item {id}")
    return _move("done" if cur["status"] == "review" else "approved")(c, role, id, note, actor)


_actor, _note, _lim = S("Who acts (default: the server role)"), S("Required for submit/reject"), I("Max rows")
_w = lambda fn: lambda c, role, **a: (lambda out: {"ok": True, **({"id": out} if isinstance(out, int) else {})})(fn(c, role=role, **a))
# name -> (fn(c, role, **args), description, input schema, roles allowed to see/call it)
TOOLS = {
    "list_projects": (lambda c, role: [dict(r) for r in c.execute("SELECT id,name,parent,status FROM project ORDER BY id")], "List projects", schema({}, []), ALL),
    "list_items": (_list_items, "List items by priority; ready=true: approved, deps done", schema(
        {"project": S(), "kind": S(), "status": STATUS, "owner": S(), "ready": {"type": "boolean"}, "limit": _lim, "label": S()}, []), ALL),
    "get_item": (_get_item, "One item with spec, deps both ways, c4 links, recent audit", schema({"id": I()}, ["id"]), ALL),
    "get_doc": (_get_doc, "A project doc (YAML) parsed, with validation errors", schema({"project": S(), "path": S("Relative path under docs_dir")}, ["project", "path"]), ALL),
    "c4_context": (lambda c, role, project, object=None, max_tokens=2000: c4_layered.context_text(c, project, object, max_tokens),
                   "C4 overview or one object with its links, connections and flows", schema({"project": S(), "object": S(), "max_tokens": I()}, ["project"]), ALL),
    "c4_flow": (lambda c, role, project, id=None: c4_layered.flow_text(c, project, id), "Numbered trace of a flow; no id lists flows", schema({"project": S(), "id": S()}, ["project"]), ALL),
    "audit": (_audit, "Recent audit rows of a project, newest first", schema({"project": S(), "limit": _lim}, ["project"]), ALL),
    "task_context": (_context, "Budgeted context bundle for a task: ticket, hard rules, c4, paths", schema({"id": I(), "budget": I("Max chars, default 12000")}, ["id"]), ALL),
    "search": (service.search, "Full-text search over items, pages and docs", schema(
        {"q": S(), "project": S(), "src": {"type": "string", "enum": ["item", "page", "doc"]}, "limit": {"type": "integer"}}, ["q"]), ALL),
    "add_item": (_w(service.add_item), "Add a task (label issue for issues); non-main roles: label issue only, as proposed", schema({"project": S(), "kind": {"type": "string", "enum": ["task", "issue"]}, "title": S(), "body": S(),
                 "priority": S(), "status": STATUS, "spec": {"type": "object"}, "label": S()}, ["project", "kind", "title"]), ALL),
    "edit_item": (_w(service.edit_item), "Edit title/body/spec/priority", schema({"id": I(), "title": S(), "body": S(), "spec": {"type": "object"}, "priority": S()}, ["id"]), MAIN),
    "item_claim": (_move("doing"), "Claim an approved item (approved -> doing)", schema({"id": I(), "actor": _actor}, ["id"]), WORK),
    "item_submit": (_move("review"), "Submit for review (doing -> review)", schema({"id": I(), "note": _note, "actor": _actor}, ["id", "note"]), WORK),
    "item_approve": (_approve, "Approve: proposed -> approved, review -> done", schema({"id": I(), "note": S(), "actor": _actor}, ["id"]), MAIN),
    "item_reject": (_move("rejected"), "Reject an item", schema({"id": I(), "note": _note}, ["id", "note"]), MAIN),
    "item_release": (_move("approved"), "Release a doing item back to approved", schema({"id": I()}, ["id"]), MAIN),
    "dep_add": (lambda c, role, id, depends_on: {"changed": service.dep(c, role, id, depends_on, True)}, "Item id depends on depends_on", schema({"id": I(), "depends_on": I()}, ["id", "depends_on"]), MAIN),
    "dep_rm": (lambda c, role, id, depends_on: {"changed": service.dep(c, role, id, depends_on, False)}, "Remove a dependency", schema({"id": I(), "depends_on": I()}, ["id", "depends_on"]), MAIN),
}


def cap(text):
    """One ceiling for every tool result: cut at a line boundary, say how much was dropped."""
    if len(text) <= CAP: return text
    foot = lambda n: f"\n… truncated, {n} more chars; narrow with limit/filters"
    keep = text[:CAP - len(foot(len(text)))]
    keep = keep[:keep.rfind("\n")] if "\n" in keep else keep
    return keep + foot(len(text) - len(keep))


def call(c, role, name, args):
    """Run one tool and return its capped result text."""
    fn, _, sch, _ = TOOLS[name]
    args = {k: v for k, v in args.items() if k in sch["properties"]}  # drops any client-sent role
    for k, v in args.items():
        t = sch["properties"][k].get("type")
        okt = {"string": isinstance(v, str), "integer": type(v) is int and abs(v) < 2**63, "boolean": isinstance(v, bool), "object": isinstance(v, dict)}.get(t, True)
        if not okt: raise ValueError(f"argument {k!r} must be {t}")
    out = fn(c, role=role, **args)
    if isinstance(out, list): text = "\n".join(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in out) or "(none)"
    else: text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)
    return cap(text)


def handle(c, role, msg):
    """Returns the response dict, or None for notifications."""
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params")
    ok = lambda r: {"jsonrpc": "2.0", "id": mid, "result": r}
    err = lambda code, m: {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": m}}
    if "id" not in msg: return None
    if mid is None or isinstance(mid, (bool, dict, list)): mid = None; return err(-32600, "invalid id")
    if not isinstance(method, str): return err(-32600, "method must be a string")
    if p is None: p = {}
    if not isinstance(p, dict): return err(-32602, "params must be an object")
    if method == "initialize":
        v = p.get("protocolVersion")
        return ok({"protocolVersion": v if v in VERSIONS else VERSIONS[0], "capabilities": {"tools": {}}, "serverInfo": {"name": f"strata-{role}", "version": "0.1"}})
    if method == "ping": return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, d, s, roles) in TOOLS.items() if role in roles]})
    if method == "tools/call":
        name, a = p.get("name"), p.get("arguments")
        if a is None: a = {}
        if not isinstance(name, str): return err(-32602, "name must be a string")
        if not isinstance(a, dict): return err(-32602, "arguments must be an object")
        if name not in TOOLS: return err(-32602, f"unknown tool {name}")
        if role not in TOOLS[name][3]:
            try: service._deny(c, role, name, None, None, {"name": name}, "tool hidden for role")  # audits tool 'denied:<name>'
            except PermissionError: pass
            return err(-32602, f"unknown tool {name}")
        try: text, bad = call(c, role, name, a), False
        except (PermissionError, ValueError, KeyError) as e:
            text, bad = f"error: {e.args[0] if isinstance(e, KeyError) else e}", True
            print(f"strata mcp: {name}: {type(e).__name__}: {text[7:]}", file=sys.stderr)
        except Exception as e:  # never crash the server on a bad call
            traceback.print_exc(file=sys.stderr); text, bad = f"{type(e).__name__}: {e}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": bad})
    return err(-32601, f"method not found: {method}")


def serve(role, db_path=None, inp=None, out=sys.stdout):
    inp = inp or sys.stdin.buffer
    c = db.init(db_path)
    def reply(r): out.write(json.dumps(r, ensure_ascii=True) + "\n"); out.flush()
    bad = lambda code, m: {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": m}}
    while line := inp.readline(MAX_LINE + 1):
        if len(line) > MAX_LINE and not line.endswith(b"\n"):
            while (rest := inp.readline(1 << 16)) and not rest.endswith(b"\n"): pass  # drain the oversized line
            reply(bad(-32600, "line too long")); continue
        try: text = line.decode("utf-8")
        except UnicodeDecodeError: reply(bad(-32700, "invalid UTF-8")); continue
        if not text.strip(): continue
        try: msg = json.loads(text)
        except (ValueError, RecursionError): reply(bad(-32700, "parse error")); continue
        r = handle(c, role, msg) if isinstance(msg, dict) else bad(-32600, "invalid request")
        if r: reply(r)
    return 0
