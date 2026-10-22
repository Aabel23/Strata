"""Write/read layer shared by CLI and MCP: role checks, audit on every write."""
import json, pathlib, re
from strata import db

ROLES = ("main", "coder", "reviewer")


def _deny(c, role, op, project, target, info, msg):
    """Audit a denied call (ids/kind/title only, never body text), then raise."""
    c.rollback()
    info = {k: (v[:80] if isinstance(v, str) else v) for k, v in (info or {}).items()}
    db.audit(c, project or "-", f"denied:{op}", target, None, info, role if role in ROLES else "invalid")
    c.commit()
    raise PermissionError(msg)


def _role(c, role, op, project=None, target=None, info=None):
    if role not in ROLES: _deny(c, role, op, project, target, info, f"unknown role {role!r}")


def _phase(c, project, phase):
    """(phase, roadmap) to store: an explicit phase goes with the running roadmap; no phase on an issue = the running phase."""
    from strata import roadmap
    act = roadmap.active(c, project)
    if phase is None: return act[::-1] if act else (None, None)
    if not isinstance(phase, int) or isinstance(phase, bool) or phase < 0: raise ValueError("phase must be an integer >= 0")
    return phase, act and act[0]


def add_item(c, role, project, kind, title, body=None, priority=None, status=None, spec=None, phase=None, label=None):
    if kind == "issue": kind, label = "task", "issue"  # alias: an issue is a task labelled issue
    if status is None: status = "approved" if label == "issue" else "open"
    info = {"kind": kind, "title": title, **({"label": label} if label else {})}
    _role(c, role, "item.add", project, None, info)
    if role != "main" and (kind, label) != ("task", "issue"): _deny(c, role, "item.add", project, None, info, f"{role} may only add issues")
    if role != "main": status = "proposed"
    if spec is not None and not isinstance(spec, dict): raise ValueError("spec must be a JSON object")
    if phase is not None or label == "issue": phase, rid = _phase(c, project, phase)
    else: rid = None
    return db.add_item(c, project, kind, title, body, priority, status, role, spec, phase, rid, label)


# (from, to) -> (roles allowed, note required). Owner/dep/version rules live in transition().
RULES = {("proposed", "approved"): ({"main"}, False), ("proposed", "rejected"): ({"main"}, True),
         ("approved", "doing"): ({"main", "coder"}, False), ("approved", "rejected"): ({"main"}, True),
         ("doing", "review"): ({"main", "coder"}, True), ("doing", "approved"): ({"main"}, False), ("doing", "rejected"): ({"main"}, True),
         ("review", "done"): ({"main"}, False), ("review", "doing"): ({"main"}, True),
         ("open", "doing"): ({"main", "coder"}, False), ("open", "done"): ({"main"}, True), ("open", "rejected"): ({"main"}, True),
         ("rejected", "proposed"): ({"main"}, False)}


def _spec(r): return json.loads(r["spec"]) if r["spec"] else {}


def _gate(spec):
    """Why a task spec is not ready to be approved ([] = ok)."""
    miss = [k for k in ("goal", "acceptance", "verify") if not spec.get(k)]
    if not (spec.get("scope") or {}).get("touch"): miss.append("scope.touch")
    return miss + (["open_questions must be empty"] if spec.get("open_questions") else [])


def transition(c, role, id, to, actor=None, note=None):
    """The one place that moves an item between statuses (CLI and MCP). Compare-and-swap on status+version; every denial is audited."""
    r = c.execute("SELECT * FROM item WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no item {id}")
    actor = actor or role
    d = lambda msg: _deny(c, role, "item.transition", r["project"], f"item:{id}", {"id": id, "from": r["status"], "to": to, "actor": actor}, msg)
    if role not in ROLES: d(f"unknown role {role!r}")
    frm = r["status"]
    if frm == "done": d("done is terminal")
    if (frm, to) not in RULES: d(f"illegal transition {frm} -> {to}")
    roles, need_note = RULES[(frm, to)]
    if role not in roles: d(f"{role} may not move {frm} -> {to}")
    if need_note and not (note or "").strip(): d(f"{frm} -> {to} needs a note")
    owner, claimed = r["owner"], r["claimed_at"]
    if to == "doing" and frm in ("approved", "open"):  # claim
        undone = [x["depends_on"] for x in c.execute("SELECT depends_on FROM item_dep d JOIN item i ON i.id=d.depends_on WHERE d.item_id=? AND i.status!='done'", (id,))]
        if undone: d(f"blocked by unfinished dependencies {undone}")
        if _spec(r).get("blocked"): d("spec.blocked is set")
        owner, claimed = actor, db.now()
    elif frm == "doing" and to == "review" and actor != owner: d(f"only the owner ({owner}) may submit")
    elif frm == "review" and to == "done":
        if actor == owner: d("owner may not approve own work")
        sub = c.execute("SELECT json_extract(after,'$.version') v FROM audit WHERE target=? AND tool='item.transition' "
                        "AND json_extract(after,'$.status')='review' ORDER BY id DESC LIMIT 1", (f"item:{id}",)).fetchone()
        if not sub or sub["v"] != r["version"]: d("item changed since submit")
    elif to == "approved" and frm == "proposed" and r["kind"] == "task" and (miss := _gate(_spec(r))):
        d("spec incomplete: " + ", ".join(miss))
    elif frm == "doing" and to == "approved": owner = claimed = None  # release
    elif frm == "rejected": owner = claimed = None
    n = c.execute("UPDATE item SET status=?,owner=?,claimed_at=?,updated_at=?,version=version+1 WHERE id=? AND status=? AND version=?",
                  (to, owner, claimed, db.now(), id, frm, r["version"])).rowcount
    if not n: d("item changed concurrently, reload and retry")
    db.audit(c, r["project"], "item.transition", f"item:{id}", {"status": frm, "owner": r["owner"]},
             {"status": to, "actor": actor, "note": note, "version": r["version"] + 1}, role)
    c.commit()


def set_item(c, role, id, status=None, priority=None):
    r = c.execute("SELECT project FROM item WHERE id=?", (id,)).fetchone()
    if role not in ROLES or (priority is not None and role != "main"):
        _deny(c, role, "item.set", r and r["project"], f"item:{id}", {"id": id, "status": status, "priority": priority}, f"{role} may not set priority" if role in ROLES else f"unknown role {role!r}")
    if not r: raise KeyError(f"no item {id}")
    if status is not None: transition(c, role, id, status)
    if priority is not None: db.set_item(c, id, None, priority, role)


def edit_item(c, role, id, title=None, body=None, spec=None, priority=None, phase=None):
    r = c.execute("SELECT project,version FROM item WHERE id=?", (id,)).fetchone()
    if role != "main": _deny(c, role, "item.edit", r and r["project"], f"item:{id}", {"id": id}, f"{role} may not edit items")
    if not r: raise KeyError(f"no item {id}")
    if spec is not None and not isinstance(spec, dict): raise ValueError("spec must be a JSON object")
    if phase is not None: phase, rid = _phase(c, r["project"], phase)
    new = {k: v for k, v in (("title", title), ("body", body), ("priority", priority), ("phase", phase), ("roadmap", phase is not None and rid or None),
                             ("spec", None if spec is None else json.dumps(spec, ensure_ascii=False))) if v is not None}
    if not new: raise ValueError("nothing to edit")
    sets = ",".join(f"{k}=?" for k in new)
    if not c.execute(f"UPDATE item SET {sets},updated_at=?,version=version+1 WHERE id=? AND version=?", (*new.values(), db.now(), id, r["version"])).rowcount:
        raise RuntimeError("item changed concurrently, reload and retry")
    db.audit(c, r["project"], "item.edit", f"item:{id}", None, {"fields": sorted(new)}, role); c.commit()


def dep(c, role, id, depends_on, add=True):
    r = c.execute("SELECT project FROM item WHERE id=?", (id,)).fetchone()
    if role != "main": _deny(c, role, "item.dep", r and r["project"], f"item:{id}", {"id": id, "depends_on": depends_on}, f"{role} may not change dependencies")
    for i in (id, depends_on):
        if not c.execute("SELECT 1 FROM item WHERE id=?", (i,)).fetchone(): raise KeyError(f"no item {i}")
    if not add:
        n = c.execute("DELETE FROM item_dep WHERE item_id=? AND depends_on=?", (id, depends_on)).rowcount
    else:
        if id == depends_on: raise ValueError("an item cannot depend on itself")
        c.execute("BEGIN IMMEDIATE")  # cycle check and insert under one write lock
        seen, todo = set(), [depends_on]
        while todo:  # does depends_on already reach id?
            x = todo.pop()
            if x == id: c.rollback(); raise ValueError(f"dependency cycle: {depends_on} already depends on {id}")
            if x not in seen: seen.add(x); todo += [y[0] for y in c.execute("SELECT depends_on FROM item_dep WHERE item_id=?", (x,))]
        n = c.execute("INSERT OR IGNORE INTO item_dep VALUES(?,?)", (id, depends_on)).rowcount
    if n: db.audit(c, r["project"], "item.dep", f"item:{id}", None, {"depends_on": depends_on, "op": "add" if add else "rm"}, role)
    c.commit()
    return bool(n)


def _out(r):
    return {**{k: r[k] for k in r.keys() if k != "spec"}, "spec": _spec(r) or None}


def list_items(c, project=None, kind=None, status=None, owner=None, ready=False, label=None):
    """Items, sorted by priority then id. ready: approved task/step whose deps are all done and spec not blocked."""
    w, a = [], []
    if kind == "issue": kind, label = "task", "issue"  # alias
    for col, v in (("project", project), ("kind", kind), ("label", label), ("status", status), ("owner", owner)):
        if v: w.append(f"{col}=?"); a.append(v)
    if ready:
        w.append("kind IN ('task','step') AND status='approved' AND NOT EXISTS(SELECT 1 FROM item_dep d JOIN item i ON i.id=d.depends_on WHERE d.item_id=item.id AND i.status!='done')")
    rows = [_out(r) for r in c.execute(f"SELECT * FROM item {'WHERE ' + ' AND '.join(w) if w else ''} ORDER BY {db.ITEM_ORDER}", a)]
    return [r for r in rows if not (ready and (r["spec"] or {}).get("blocked"))]


def get_item(c, id):
    r = c.execute("SELECT * FROM item WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no item {id}")
    q = lambda a, b: [dict(x) for x in c.execute(f"SELECT i.id,i.title,i.status FROM item_dep d JOIN item i ON i.id=d.{a} WHERE d.{b}=? ORDER BY i.id", (id,))]
    return {**_out(r), "depends_on": q("depends_on", "item_id"), "blocks": q("item_id", "depends_on")}


SRC_TABLE = {"item": "item", "page": "page", "doc": "doc"}


def search(c, q, project=None, src=None, limit=30, role="main"):
    """FTS5 over item/page/doc. Terms are quoted (no FTS syntax from input), last one is a prefix."""
    _role(c, role, "search", project)
    if src is not None and src not in SRC_TABLE: raise ValueError(f"unknown src {src!r}")
    try: limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError): raise ValueError("bad limit") from None
    terms = re.findall(r"\w+", db.fold(q or ""))
    if not terms: raise ValueError("empty q")
    match = " ".join(f'"{t}"' for t in terms) + "*"
    sql, args = "SELECT src,ref,project,snippet(search,1,'','','…',12) snippet FROM search WHERE search MATCH ?", [match]
    if project: sql += " AND project=?"; args.append(project)
    sql += " AND src IN (%s)" % ",".join("?" * len(SRC_TABLE)); args += SRC_TABLE  # index may still hold legacy src rows
    if src: sql += " AND src=?"; args.append(src)
    args.append(limit)
    hits = [dict(r) for r in c.execute(sql + " ORDER BY bm25(search,10.0,1.0) LIMIT ?", args)]
    for h in hits:  # real title/key from the source row (the index holds the folded copy)
        col = {"item": "kind", "page": "slug", "doc": "path"}[h["src"]]
        key = "id" if h["src"] == "item" else "rowid"
        r = c.execute(f"SELECT title, {col} AS k FROM {SRC_TABLE[h['src']]} WHERE {key}=?", (h["ref"],)).fetchone()
        h["title"], h["key"] = (r["title"], r["k"]) if r else ("", "")
    return hits

