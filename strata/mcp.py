"""MCP server over stdio (JSON-RPC 2.0, one JSON message per line). Role is fixed at launch; clients cannot pass one."""
import json, os, pathlib, sys, traceback
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
    """One compact JSON line per item (no body/spec: get_item has those), so a whole board fits under the cap."""
    rows, limit = service.list_items(c, project, kind, status, owner, ready, label), max(1, limit)
    keep = ("id", "kind", "label", "status", "priority", "owner", "title") if project else ("id", "project", "kind", "label", "status", "priority", "owner", "title")
    out = [json.dumps({k: r[k] for k in keep if r.get(k) is not None}, ensure_ascii=False) for r in rows[:limit]]
    return out + ([f"… {len(rows) - limit} more; raise limit or add filters"] if len(rows) > limit else [])


def _list_docs(c, role, project, kind=None):
    return [json.dumps({k: r[k] for k in r.keys() if r[k] is not None}, ensure_ascii=False) for r in c.execute(
        "SELECT path,title,kind,status,feature,summary FROM doc WHERE project=? AND status!='missing' AND (? IS NULL OR kind=?) ORDER BY kind,ord,path", (project, kind, kind))]


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


# (from, to) -> the tool that makes that move; used to tell a denied caller what it can do instead
VERB = {("approved", "doing"): "item_claim", ("open", "doing"): "item_claim", ("doing", "review"): "item_submit", ("proposed", "approved"): "item_approve",
        ("review", "done"): "item_approve", ("review", "doing"): "item_rework", ("doing", "approved"): "item_release", ("open", "done"): "item_close", ("rejected", "proposed"): "item_reopen"}


def _next(c, role, id):
    """' (item #7 is doing, owner bot; coder can next: item_submit -> review)' for error messages."""
    r = c.execute("SELECT status,owner FROM item WHERE id=?", (id,)).fetchone()
    if not r: return ""
    verb = lambda f, t: VERB.get((f, t)) or ("item_reject" if t == "rejected" else None)
    moves = [f"{verb(f, t)} -> {t}" for (f, t), (roles, _) in service.RULES.items() if f == r["status"] and role in roles and verb(f, t) and role in TOOLS[verb(f, t)][3]]
    return f" (item #{id} is {r['status']}, owner {r['owner'] or '-'}; {role} can next: {', '.join(moves) or 'nothing'})"


def _move(to, frm=None):
    def f(c, role, id, note=None, actor=None):
        if frm:
            cur = c.execute("SELECT status FROM item WHERE id=?", (id,)).fetchone()
            if not cur: raise KeyError(f"no item {id}")
            if cur["status"] != frm: raise ValueError(f"only from {frm}" + _next(c, role, id))
        try: service.transition(c, role, id, to, actor, note)
        except PermissionError as e: raise PermissionError(f"{e}{_next(c, role, id)}") from None
        return {"ok": True, "status": to}
    return f


def _link(c, role, project, object, item, remove=False):
    return {"changed": (db.unlink if remove else db.link)(c, project, object, item)}


def _approve(c, role, id, note=None, actor=None):
    cur = c.execute("SELECT status FROM item WHERE id=?", (id,)).fetchone()
    if not cur: raise KeyError(f"no item {id}")
    if cur["status"] not in ("proposed", "review"): raise ValueError("approve only from proposed or review" + _next(c, role, id))
    return _move("done" if cur["status"] == "review" else "approved")(c, role, id, note, actor)


_actor, _note, _lim = S("Who acts (default: the server role)"), S("Required: what was done / why"), I("Max rows")
_proj = S("Project id; default: the project whose root contains the server's working directory")
_id = I("Item id (the number after #)")
_prio = S("high | medium | low (also p0..p3, urgent); sorts the board")
_spec = {"type": "object", "description": "Task contract. A proposed task can only be approved when goal, acceptance, verify and scope.touch are set and open_questions is empty. "
         "Keys: goal (string), acceptance (list of checkable criteria), verify (commands/steps that prove it), scope {module, touch: [repo-relative paths], forbid: [paths]}, "
         "open_questions (list), blocked (true keeps it off the ready list). On edit_item the given spec replaces the stored one"}
_w = lambda fn: lambda c, role, **a: (lambda out: {"ok": True, **({"id": out, "project": a.get("project")} if isinstance(out, int) else {})})(fn(c, role=role, **a))
# name -> (fn(c, role, **args), description, input schema, roles allowed to see/call it)
TOOLS = {
    "list_projects": (lambda c, role: [dict(r) for r in c.execute("SELECT id,name,parent,status,root FROM project ORDER BY id")], "List registered projects (id, name, parent, root)", schema({}, []), ALL),
    "list_items": (_list_items, "The board: one compact line per task/issue (no body), issues first then by priority. ready=true: approved, all dependencies done, not blocked — what can be claimed now. "
                   "Without project: all projects. Use get_item or task_context for the details of one", schema(
        {"project": S("Project id; omit for all projects"), "kind": {"type": "string", "enum": ["task", "issue", "step", "gate"]}, "status": STATUS, "owner": S("Actor who claimed it"),
         "ready": {"type": "boolean"}, "limit": I("Max rows, default 50"), "label": S("e.g. issue")}, []), ALL),
    "get_item": (_get_item, "One item in full: body, spec, dependencies both ways, linked C4 objects, last 5 audit rows", schema({"id": _id}, ["id"]), ALL),
    "list_docs": (_list_docs, "Docs of a project (path, title, kind, status, summary); read one with get_doc", schema(
        {"project": _proj, "kind": {"type": "string", "enum": ["research", "architect", "review", "plan", "other"]}}, []), ALL),
    "get_doc": (_get_doc, "A project doc (YAML) parsed, with validation errors. Paths come from list_docs or search", schema({"project": _proj, "path": S("Path relative to the project's docs dir, e.g. research/x.yaml")}, ["path"]), ALL),
    "c4_context": (lambda c, role, project, object=None, max_tokens=2000: c4_layered.context_text(c, project, object, max_tokens),
                   "C4 map: overview of the project, or one object with its links, connections and flows", schema({"project": _proj, "object": S("Object id from the overview"), "max_tokens": I("Default 2000")}, []), ALL),
    "c4_flow": (lambda c, role, project, id=None: c4_layered.flow_text(c, project, id), "Numbered step trace of one flow; without id, lists the flows", schema({"project": _proj, "id": S("Flow id")}, []), ALL),
    "audit": (_audit, "Recent audit rows of a project, newest first (who changed what, including denied attempts)", schema({"project": _proj, "limit": _lim}, []), ALL),
    "task_context": (_context, "Everything a worker needs to start one task, in one budgeted text: ticket spec, dependencies, the project's hard rules, linked C4 objects, paths to touch", schema({"id": _id, "budget": I("Max chars, default 12000")}, ["id"]), ALL),
    "search": (service.search, "Full-text search over items, pages and docs. Hits give src and ref: for src=item, ref is the item id (get_item); for src=doc, key is the path (get_doc)", schema(
        {"q": S("Words; the last one matches as a prefix"), "project": S("Project id; omit for all projects"), "src": {"type": "string", "enum": ["item", "page", "doc"]}, "limit": I("Default 30, max 100")}, ["q"]), ALL),
    "add_item": (_w(service.add_item), "Add a task, or an issue (kind=issue). Role main: any item, default status open (issues: approved). Other roles: issues only, always created as proposed for the user to approve",
                 schema({"project": _proj, "kind": {"type": "string", "enum": ["task", "issue"]}, "title": S("One line"), "body": S("Markdown: context, evidence, file:line"),
                         "priority": _prio, "status": STATUS, "spec": _spec, "label": S("issue = same as kind=issue")}, ["kind", "title"]), ALL),
    "edit_item": (_w(service.edit_item), "Edit title/body/spec/priority of an item (status moves have their own item_* tools)", schema({"id": _id, "title": S("New title"), "body": S("New body (replaces the old one)"), "spec": _spec, "priority": _prio}, ["id"]), MAIN),
    "item_claim": (_move("doing"), "Start work: approved (or open) -> doing; the actor becomes owner. Fails while a dependency is not done", schema({"id": _id, "actor": _actor}, ["id"]), WORK),
    "item_submit": (_move("review"), "Hand in for review: doing -> review. Only the owner (same actor as the claim); note = what changed and the verification evidence", schema({"id": _id, "note": _note, "actor": _actor}, ["id", "note"]), WORK),
    "item_approve": (_approve, "Approve: proposed -> approved (task spec must be complete), or review -> done (not by the owner)", schema({"id": _id, "note": S("Optional comment for the audit trail"), "actor": _actor}, ["id"]), MAIN),
    "item_rework": (_move("doing", "review"), "Send a reviewed item back to its owner: review -> doing", schema({"id": _id, "note": _note}, ["id", "note"]), MAIN),
    "item_close": (_move("done", "open"), "Close an open item without the review path: open -> done", schema({"id": _id, "note": _note}, ["id", "note"]), MAIN),
    "item_reject": (_move("rejected"), "Reject an item (any status except review/done)", schema({"id": _id, "note": _note}, ["id", "note"]), MAIN),
    "item_reopen": (_move("proposed", "rejected"), "Bring a rejected item back: rejected -> proposed", schema({"id": _id, "note": S("Optional comment for the audit trail")}, ["id"]), MAIN),
    "item_release": (_move("approved"), "Drop a claim: doing -> approved, owner cleared", schema({"id": _id}, ["id"]), MAIN),
    "dep_add": (lambda c, role, id, depends_on: {"changed": service.dep(c, role, id, depends_on, True)}, "Item id depends on depends_on (id cannot be claimed until depends_on is done)", schema({"id": _id, "depends_on": I("Id of the item that must be done first")}, ["id", "depends_on"]), MAIN),
    "dep_rm": (lambda c, role, id, depends_on: {"changed": service.dep(c, role, id, depends_on, False)}, "Remove a dependency", schema({"id": _id, "depends_on": I("Id it no longer depends on")}, ["id", "depends_on"]), MAIN),
    "c4_link": (_link, "Attach an item to a C4 object so task_context carries that part of the map (remove=true detaches)", schema({"project": _proj, "object": S("C4 object id"), "item": _id, "remove": {"type": "boolean"}}, ["object", "item"]), MAIN),
}
READS = {"list_projects", "list_items", "get_item", "list_docs", "get_doc", "c4_context", "c4_flow", "audit", "task_context", "search"}
CWD_PROJECT = {"list_docs", "get_doc", "c4_context", "c4_flow", "audit", "add_item", "c4_link"}  # project omitted -> the project containing the server cwd

FLOW = {"main": "You are the coordinator: add_item/edit_item, approve (item_approve), send back (item_rework), reject, close, release, dependencies, c4_link.",
        "coder": "You are a coder: list_items(ready=true) -> task_context(id) -> item_claim(id, actor) -> do the work -> item_submit(id, note, actor) with the same actor. "
                 "You cannot approve or mark done; found problems go in as add_item(kind=issue), created as proposed.",
        "reviewer": "You are a reviewer: read with get_item/task_context/audit; report findings as add_item(kind=issue), created as proposed. You cannot change item status."}


def instructions(c, role):
    here = db.project_for_path(c, os.getcwd())
    return ("Strata holds the tasks/issues, docs and C4 maps of registered projects. Item ids are global integers. "
            "Lifecycle: proposed -> approved -> doing -> review -> done (also open, rejected). "
            + FLOW[role] + " Read first: list_items for the board (ready=true = claimable now), get_item for one item, search for anything by words, "
            "list_docs/get_doc for documents, c4_context/c4_flow for architecture. "
            + (f"Tools with an optional `project` default to `{here}` (this working directory)." if here else "This working directory is not inside a registered project: pass `project` (see list_projects).")
            + " A failed call says why and what this role can do next; results are capped at 8000 chars, so narrow with filters.")


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
    props = sch["properties"]
    if extra := sorted(k for k in args if k not in props and k != "role"):  # a client-sent role is dropped silently: the role is fixed at launch
        raise ValueError(f"unknown argument {', '.join(extra)}; {name} takes: {', '.join(props) or 'no arguments'}")
    args = {k: int(v) if props[k].get("type") == "integer" and isinstance(v, str) and v.lstrip("-").isdigit() and len(v) < 19 else v for k, v in args.items() if k in props and v is not None}
    if miss := [k for k in sch["required"] if k not in args]: raise ValueError(f"missing required argument {', '.join(miss)}")
    if "project" in props:
        if "project" not in args and name in CWD_PROJECT:
            args["project"] = db.project_for_path(c, os.getcwd())
            if not args["project"]: raise ValueError("pass project: the working directory is not inside a registered project (see list_projects)")
        elif "project" in args and isinstance(args["project"], str) and not db.project_exists(c, args["project"]):
            raise KeyError(f"no project {args['project']}; known: {', '.join(r[0] for r in c.execute('SELECT id FROM project ORDER BY id'))}")
    for k, v in args.items():
        t = props[k].get("type")
        if "enum" in props[k] and isinstance(v, str) and v not in props[k]["enum"]: raise ValueError(f"argument {k!r} must be one of: {', '.join(props[k]['enum'])}")
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
        return ok({"protocolVersion": v if v in VERSIONS else VERSIONS[0], "capabilities": {"tools": {}}, "serverInfo": {"name": f"strata-{role}", "version": "0.2"}, "instructions": instructions(c, role)})
    if method == "ping": return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": s, "annotations": {"readOnlyHint": n in READS, "destructiveHint": False, "openWorldHint": False}}
                             for n, (_, d, s, roles) in TOOLS.items() if role in roles]})
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
