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


PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def add_project(c, id, name, root=None, docs_dir=None, parent=None, description=None):
    """User/CLI project create: id is a lowercase slug, root/docs_dir must be existing folders, parent an existing project."""
    id, name = (id or "").strip(), (name or "").strip()
    if not PROJECT_ID.match(id): raise ValueError("id: 1-40 chars, lowercase letters, digits, - or _, starting with a letter or digit")
    if not name: raise ValueError("name is required")
    if db.project_exists(c, id): raise ValueError(f"project {id} already exists")
    root, docs_dir, description = (x.strip() or None if isinstance(x, str) else None for x in (root, docs_dir, description))
    root, docs_dir = _paths(c, root, docs_dir, parent)
    db.add_project(c, id, name, root, docs_dir, parent or None, description)


def _paths(c, root, docs_dir, parent):
    """Shared add/edit validation; returns normalised (root, docs_dir)."""
    if parent and not db.project_exists(c, parent): raise ValueError(f"parent {parent} does not exist")
    if root and not pathlib.Path(root).expanduser().is_absolute(): raise ValueError("root must be an absolute path")
    if root and not pathlib.Path(root).expanduser().is_dir(): raise ValueError(f"root {root} is not a folder")
    if docs_dir and root and not pathlib.Path(docs_dir).is_absolute(): docs_dir = str(pathlib.Path(root) / docs_dir)
    if docs_dir and not pathlib.Path(docs_dir).expanduser().is_absolute(): raise ValueError("docs dir must be absolute, or relative to root")
    return root and str(pathlib.Path(root).expanduser()), docs_dir and str(pathlib.Path(docs_dir).expanduser())


def edit_project(c, id, name=None, root=None, docs_dir=None, parent=None, description=None):
    """Edit a project. None = keep; "" clears root/docs_dir/parent/description. Same checks as add_project, plus no parent cycle."""
    old = db.get_project(c, id)
    if old is None: raise KeyError(f"no project {id}")
    new = {k: (v.strip() or None) for k, v in (("name", name), ("root", root), ("docs_dir", docs_dir), ("parent", parent), ("description", description)) if isinstance(v, str)}
    if "name" in new and not new["name"]: raise ValueError("name is required")
    if not new: raise ValueError("nothing to edit")
    if new.get("parent"):
        x = new["parent"]
        while x:  # walk up from the new parent; reaching id means a cycle (or self)
            if x == id: raise ValueError("parent would create a cycle")
            x = db.get_project_parent(c, x)
    d = new.get("docs_dir")
    if d and not pathlib.Path(d).is_absolute() and not new.get("root") and old["root"]: d = str(pathlib.Path(old["root"]) / d)  # relative to the current root
    r, d = _paths(c, new.get("root"), d, new.get("parent"))
    for k, v in (("root", r), ("docs_dir", d)):
        if k in new: new[k] = v
    c.execute(f"UPDATE project SET {','.join(f'{k}=:{k}' for k in new)} WHERE id=:id", {**new, "id": id})
    db.audit(c, id, "project.edit", id, {k: old[k] for k in new}, new, "main"); c.commit()


def delete_project(c, id, confirm):
    """Delete only when `confirm` repeats the project id (the viewer asks the user to type it)."""
    if confirm != id: raise ValueError("confirmation does not match the project id")
    if db.project_exists(c, id): db.backup(c)  # no backup, no delete
    db.delete_project(c, id)


def add_item(c, role, project, kind, title, body=None, priority=None, status=None, spec=None, label=None):
    if kind == "issue": kind, label = "task", "issue"  # alias: an issue is a task labelled issue
    if status is None: status = "approved" if label == "issue" else "open"
    info = {"kind": kind, "title": title, **({"label": label} if label else {})}
    _role(c, role, "item.add", project, None, info)
    if role != "main" and (kind, label) != ("task", "issue"): _deny(c, role, "item.add", project, None, info, f"{role} may only add issues")
    if role != "main": status = "proposed"
    if spec is not None and not isinstance(spec, dict): raise ValueError("spec must be a JSON object")
    return db.add_item(c, project, kind, title, body, priority, status, role, spec, label=label)


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


def transition(c, role, id, to, actor=None, note=None, _commit=True):
    """The one place that moves an item between statuses (CLI and MCP). Compare-and-swap on status+version; every denial is audited."""
    r = db.get_item(c, id)
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
        undone = db.get_undone_deps(c, id)
        if undone: d(f"blocked by unfinished dependencies {undone}")
        if _spec(r).get("blocked"): d("spec.blocked is set")
        owner, claimed = actor, db.now()
    elif frm == "doing" and to == "review" and actor != owner: d(f"only the owner ({owner}) may submit")
    elif frm == "review" and to == "done":
        if actor == owner: d("owner may not approve own work")
        sub_v = db.get_item_last_audit_version(c, id, "review")
        if sub_v is None or sub_v != r["version"]: d("item changed since submit")
    elif to == "approved" and frm == "proposed" and r["kind"] == "task" and (miss := _gate(_spec(r))):
        d("spec incomplete: " + ", ".join(miss))
    elif frm == "doing" and to == "approved": owner = claimed = None  # release
    elif frm == "rejected": owner = claimed = None
    n = db.update_item_transition(c, id, frm, to, owner, claimed, r["version"])
    if not n: d("item changed concurrently, reload and retry")
    db.audit(c, r["project"], "item.transition", f"item:{id}", {"status": frm, "owner": r["owner"]},
             {"status": to, "actor": actor, "note": note, "version": r["version"] + 1}, role)
    if _commit: c.commit()


def set_item(c, role, id, status=None, priority=None):
    r = db.get_item_project(c, id)
    if role not in ROLES or (priority is not None and role != "main"):
        _deny(c, role, "item.set", r and r["project"], f"item:{id}", {"id": id, "status": status, "priority": priority}, f"{role} may not set priority" if role in ROLES else f"unknown role {role!r}")
    if not r: raise KeyError(f"no item {id}")
    try:  # one commit for both writes (db.set_item commits at its end); denials commit their own audit row inside _deny
        if status is not None: transition(c, role, id, status, _commit=priority is None)
        if priority is not None: db.set_item(c, id, None, priority, role)
    except Exception:
        c.rollback(); raise


def edit_item(c, role, id, title=None, body=None, spec=None, priority=None):
    r = db.get_item_project(c, id)
    if role != "main": _deny(c, role, "item.edit", r and r["project"], f"item:{id}", {"id": id}, f"{role} may not edit items")
    if not r: raise KeyError(f"no item {id}")
    if spec is not None and not isinstance(spec, dict): raise ValueError("spec must be a JSON object")
    new = {k: v for k, v in (("title", title), ("body", body), ("priority", priority),
                             ("spec", spec)) if v is not None}
    if not new: raise ValueError("nothing to edit")
    if not db.update_item_fields(c, id, r["version"], new):
        raise RuntimeError("item changed concurrently, reload and retry")
    db.audit(c, r["project"], "item.edit", f"item:{id}", None, {"fields": sorted(new)}, role); c.commit()


def delete_item(c, role, id):
    """Hard delete: the row, its deps in both directions and its C4 links. The audit row keeps what was removed."""
    r = db.get_item(c, id)
    if role != "main": _deny(c, role, "item.delete", r and r["project"], f"item:{id}", {"id": id}, f"{role} may not delete items")
    if not r: raise KeyError(f"no item {id}")
    try:
        cascade = db.delete_item_cascade(c, id, r["project"])
        db.audit(c, r["project"], "item.delete", f"item:{id}", {k: r[k] for k in r.keys()}, cascade, role)
        c.commit()
    except BaseException: c.rollback(); raise


def dep(c, role, id, depends_on, add=True):
    r = db.get_item_project(c, id)
    if role != "main": _deny(c, role, "item.dep", r and r["project"], f"item:{id}", {"id": id, "depends_on": depends_on}, f"{role} may not change dependencies")
    for i in (id, depends_on):
        if not db.get_item_project(c, i): raise KeyError(f"no item {i}")
    if not add:
        n = db.remove_item_dep(c, id, depends_on)
    else:
        if id == depends_on: raise ValueError("an item cannot depend on itself")
        c.execute("BEGIN IMMEDIATE")  # cycle check and insert under one write lock
        seen, todo = set(), [depends_on]
        while todo:  # does depends_on already reach id?
            x = todo.pop()
            if x == id: c.rollback(); raise ValueError(f"dependency cycle: {depends_on} already depends on {id}")
            if x not in seen: seen.add(x); todo += [y["id"] for y in db.get_item_deps(c, x, "depends_on")]
        n = db.add_item_dep(c, id, depends_on)
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
    rows = [_out(r) for r in db.list_items(c, where_clauses=w, args=a)]
    return [r for r in rows if not (ready and (r["spec"] or {}).get("blocked"))]


def get_item(c, id):
    r = db.get_item(c, id)
    if not r: raise KeyError(f"no item {id}")
    return {**_out(r), "depends_on": db.get_item_deps(c, id, "depends_on"), "blocks": db.get_item_deps(c, id, "blocks")}


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

