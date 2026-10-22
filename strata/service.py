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


def add_item(c, role, project, kind, title, body=None, priority=None, status="open", spec=None, phase=None):
    info = {"kind": kind, "title": title}
    _role(c, role, "item.add", project, None, info)
    if role != "main" and kind != "issue": _deny(c, role, "item.add", project, None, info, f"{role} may only add issues")
    if role != "main": status = "proposed"
    if spec is not None and not isinstance(spec, dict): raise ValueError("spec must be a JSON object")
    if phase is not None or kind == "issue": phase, rid = _phase(c, project, phase)
    else: rid = None
    return db.add_item(c, project, kind, title, body, priority, status, role, spec, phase, rid)


# (from, to) -> (roles allowed, note required). Owner/dep/version rules live in transition().
RULES = {("proposed", "approved"): ({"main"}, False), ("proposed", "rejected"): ({"main"}, True),
         ("approved", "doing"): ({"main", "coder"}, False), ("approved", "rejected"): ({"main"}, True),
         ("doing", "review"): ({"main", "coder"}, True), ("doing", "approved"): ({"main"}, False), ("doing", "rejected"): ({"main"}, True),
         ("review", "done"): ({"main"}, False), ("review", "doing"): ({"main"}, True),
         ("open", "doing"): ({"main", "coder"}, False), ("open", "done"): ({"main"}, True), ("open", "rejected"): ({"main"}, True),
         ("rejected", "proposed"): ({"main"}, False)}
PRIO = "CASE lower(coalesce(priority,'')) WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'high' THEN 1 WHEN 'p2' THEN 2 WHEN 'medium' THEN 2 WHEN 'p3' THEN 3 WHEN 'low' THEN 3 ELSE 9 END"


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


def list_items(c, project=None, kind=None, status=None, owner=None, ready=False):
    """Items, sorted by priority then id. ready: approved task/step whose deps are all done and spec not blocked."""
    w, a = [], []
    for col, v in (("project", project), ("kind", kind), ("status", status), ("owner", owner)):
        if v: w.append(f"{col}=?"); a.append(v)
    if ready:
        w.append("kind IN ('task','step') AND status='approved' AND NOT EXISTS(SELECT 1 FROM item_dep d JOIN item i ON i.id=d.depends_on WHERE d.item_id=item.id AND i.status!='done')")
    rows = [_out(r) for r in c.execute(f"SELECT * FROM item {'WHERE ' + ' AND '.join(w) if w else ''} ORDER BY {PRIO},id", a)]
    return [r for r in rows if not (ready and (r["spec"] or {}).get("blocked"))]


def get_item(c, id):
    r = c.execute("SELECT * FROM item WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no item {id}")
    q = lambda a, b: [dict(x) for x in c.execute(f"SELECT i.id,i.title,i.status FROM item_dep d JOIN item i ON i.id=d.{a} WHERE d.{b}=? ORDER BY i.id", (id,))]
    return {**_out(r), "depends_on": q("depends_on", "item_id"), "blocks": q("item_id", "depends_on")}


def add_decision(c, role, project, title, context, decision, consequences, rejected, supersedes=None):
    info = {"title": title, "supersedes": supersedes}
    _role(c, role, "decision.add", project, None, info)
    if not isinstance(rejected, str): raise ValueError("rejected must be a string")
    if rejected.strip() in ("", "[]"): raise ValueError("rejected options required")
    if supersedes is not None and role != "main": _deny(c, role, "decision.add", project, None, info, f"{role} may not supersede a decision")
    if not c.execute("SELECT 1 FROM project WHERE id=?", (project,)).fetchone(): raise KeyError(f"no project {project}")
    status = "accepted" if role == "main" else "proposed"
    old = None
    if supersedes is not None:
        old = c.execute("SELECT status FROM decision WHERE id=? AND project=?", (supersedes, project)).fetchone()
        if not old: raise KeyError(f"no decision {supersedes} in project {project}")
    try:
        cur = c.execute("INSERT INTO decision(project,title,status,context,decision,consequences,rejected_options,supersedes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (project, title, status, context, decision, consequences, rejected.strip(), supersedes, db.now()))
        if old: c.execute("UPDATE decision SET status='superseded' WHERE id=?", (supersedes,))
        db.audit(c, project, "decision.add", f"decision:{cur.lastrowid}", None,
                 {"title": title, "status": status, "supersedes": supersedes}, role)
        c.commit()
    except Exception: c.rollback(); raise
    return cur.lastrowid


def set_decision_status(c, role, id, status):
    r = c.execute("SELECT project,status FROM decision WHERE id=?", (id,)).fetchone()
    _role(c, role, "decision.set", r and r["project"], f"decision:{id}", {"id": id, "status": status})
    if role != "main": _deny(c, role, "decision.set", r and r["project"], f"decision:{id}", {"id": id, "status": status}, f"{role} may not change decision status")
    if not r: raise KeyError(f"no decision {id}")
    c.execute("UPDATE decision SET status=? WHERE id=?", (status, id))  # CHECK rejects bad status
    db.audit(c, r["project"], "decision.set", f"decision:{id}", {"status": r["status"]}, {"status": status}, role)
    c.commit()


SRC_TABLE = {"item": "item", "decision": "decision", "page": "page", "doc": "doc"}


def search(c, q, project=None, src=None, limit=30, role="main"):
    """FTS5 over item/decision/page/doc. Terms are quoted (no FTS syntax from input), last one is a prefix."""
    _role(c, role, "search", project)
    if src is not None and src not in SRC_TABLE: raise ValueError(f"unknown src {src!r}")
    try: limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError): raise ValueError("bad limit") from None
    terms = re.findall(r"\w+", db.fold(q or ""))
    if not terms: raise ValueError("empty q")
    match = " ".join(f'"{t}"' for t in terms) + "*"
    sql, args = "SELECT src,ref,project,snippet(search,1,'','','…',12) snippet FROM search WHERE search MATCH ?", [match]
    if project: sql += " AND project=?"; args.append(project)
    if src: sql += " AND src=?"; args.append(src)
    args.append(limit)
    hits = [dict(r) for r in c.execute(sql + " ORDER BY bm25(search,10.0,1.0) LIMIT ?", args)]
    for h in hits:  # real title/key from the source row (the index holds the folded copy)
        col = {"item": "kind", "decision": "''", "page": "slug", "doc": "path"}[h["src"]]
        key = "id" if h["src"] in ("item", "decision") else "rowid"
        r = c.execute(f"SELECT title, {col} AS k FROM {SRC_TABLE[h['src']]} WHERE {key}=?", (h["ref"],)).fetchone()
        h["title"], h["key"] = (r["title"], r["k"]) if r else ("", "")
    return hits


# ---- C4 canvas data ----
def add_c4_port(c, role, project, object_id, id, name, direction, kind=None, schema=None):
    info = {"object": object_id, "id": id, "name": name, "direction": direction, "kind": kind}
    _role(c, role, "c4.port.add", project, f"c4_port:{id}", info)
    if role != "main": _deny(c, role, "c4.port.add", project, f"c4_port:{id}", info, f"{role} may not edit C4")
    if direction not in ("input", "output"): raise ValueError("direction must be input or output")
    if not all(isinstance(v, str) and v.strip() for v in (id, object_id, name)): raise ValueError("port id, object, and name are required")
    if schema is not None and not isinstance(schema, (dict, list)): raise ValueError("port schema must be an object or array")
    if not c.execute("SELECT 1 FROM c4_object WHERE project=? AND id=?", (project, object_id)).fetchone(): raise KeyError(f"no C4 object {object_id!r} in project {project!r}")
    c.execute("INSERT INTO c4_port(project,id,object_id,name,direction,kind,schema_json) VALUES(?,?,?,?,?,?,?)",
              (project, id, object_id, name, direction, kind, json.dumps(schema, ensure_ascii=False) if schema is not None else None))
    db.audit(c, project, "c4.port.add", f"c4_port:{id}", None, info, role); c.commit()


def list_c4_ports(c, project, object_id=None):
    sql = "SELECT id,object_id AS object,name,direction,kind,schema_json FROM c4_port WHERE project=?"
    args = [project]
    if object_id is not None: sql += " AND object_id=?"; args.append(object_id)
    out = []
    for r in c.execute(sql + " ORDER BY object_id,id", args):
        d = dict(r)
        if d["schema_json"] is not None: d["schema"] = json.loads(d.pop("schema_json"))
        else: d.pop("schema_json")
        out.append(d)
    return out


def set_c4_kind(c, role, project, object_id, kind):
    info = {"object": object_id, "kind": kind}
    _role(c, role, "c4.kind.set", project, f"c4_object:{object_id}", info)
    if role != "main": _deny(c, role, "c4.kind.set", project, f"c4_object:{object_id}", info, f"{role} may not edit C4")
    if kind is not None and (not isinstance(kind, str) or not kind.strip()): raise ValueError("kind must be a non-empty string or null")
    before = c.execute("SELECT kind FROM c4_object WHERE project=? AND id=?", (project, object_id)).fetchone()
    if not before: raise KeyError(f"no C4 object {object_id!r} in project {project!r}")
    c.execute("UPDATE c4_object SET kind=? WHERE project=? AND id=?", (kind, project, object_id))
    db.audit(c, project, "c4.kind.set", f"c4_object:{object_id}", {"kind": before["kind"]}, {"kind": kind}, role); c.commit()


# C4 HTTP edits use the same transactional service boundary as CLI writes.
C4_OBJECT_FIELDS = {"type", "name", "parent", "technology", "description", "tags", "links", "status",
                    "responsibilities", "state", "kind"}
C4_PORT_FIELDS = {"name", "direction", "kind", "schema"}
C4_LINK_FIELDS = {"from", "to", "name", "technology", "status", "direction", "tags", "description",
                  "feature", "interface", "payload", "kind", "from_port", "to_port"}


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{label} must be a non-empty string")


def _validate_port(port):
    for key in ("id", "name", "direction"): _required_text(port.get(key), f"port {key}")
    if port["direction"] not in ("input", "output"): raise ValueError("port direction must be input or output")
    if port.get("kind") is not None: _required_text(port["kind"], "port kind")
    if port.get("schema") is not None and not isinstance(port["schema"], (dict, list)): raise ValueError("port schema must be an object or array")


def _validate_link(link):
    for key in ("id", "from", "to"): _required_text(link.get(key), f"link {key}")
    for key in ("name", "technology", "status", "direction", "description", "feature", "interface", "kind", "from_port", "to_port"):
        if link.get(key) is not None and not isinstance(link[key], str): raise ValueError(f"link {key} must be a string")
    if link.get("tags") is not None and (not isinstance(link["tags"], list) or not all(isinstance(v, str) for v in link["tags"])):
        raise ValueError("link tags must be an array of strings")
    if link.get("payload") is not None and not isinstance(link["payload"], dict): raise ValueError("link payload must be an object")


def _validate_object(obj):
    for key in ("id", "type", "name"): _required_text(obj.get(key), f"object {key}")
    if obj.get("parent") is not None and not isinstance(obj["parent"], str): raise ValueError("object parent must be a string or null")
    for key in ("technology", "description", "status", "state", "kind"):
        if obj.get(key) is not None and not isinstance(obj[key], str): raise ValueError(f"object {key} must be a string")
    for key in ("tags", "links", "responsibilities"):
        if obj.get(key) is not None and (not isinstance(obj[key], list) or not all(isinstance(v, str) for v in obj[key])):
            raise ValueError(f"object {key} must be an array of strings")


def _c4_mutation(c, project, role, op, mutate):
    from strata import c4
    _role(c, role, op, project)
    if role != "main": _deny(c, role, op, project, None, {}, f"{role} may not edit C4")
    if not c.execute("SELECT 1 FROM c4_meta WHERE project=?", (project,)).fetchone(): raise KeyError(f"no C4 model for project {project!r}")
    c.execute("BEGIN IMMEDIATE")
    try:
        m = c4.read_model(c, project)
        meta = c.execute("SELECT root FROM c4_meta WHERE project=?", (project,)).fetchone()
        change = mutate(m)
        result, target = change[:2]
        m["interfaces"] = [i for o in m["objects"] for i in o.get("interfaces", [])]
        errs = c4.check(m, pathlib.Path(meta["root"] or "."))[0]
        if errs: raise ValueError("; ".join(errs[:4]))
        _store_c4_model(c, project, m)
        before, after = change[2:] if len(change) == 4 else (None, result)
        db.audit(c, project, op, target, before, after, role)
        c.commit()
        return result
    except Exception:
        c.rollback()
        raise


def _store_c4_model(c, project, m):
    """Replace one validated project's relational C4 rows, preserving its meta and task links."""
    j = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None
    for table in ("c4_connection", "c4_flow", "c4_interface", "c4_port", "c4_object"):
        c.execute(f"DELETE FROM {table} WHERE project=?", (project,))
    for o in m["objects"]:
        c.execute("INSERT INTO c4_object(id,project,type,name,parent,technology,description,tags,links,status,responsibilities,state,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (o["id"], project, o.get("type"), o.get("name"), o.get("parent"), o.get("technology"), o.get("description"),
                   j(o.get("tags")), j(o.get("links")), o.get("status"), j(o.get("responsibilities")), o.get("state"), o.get("kind")))
    for o in m["objects"]:
        for p in o.get("ports") or []:
            c.execute("INSERT INTO c4_port(project,id,object_id,name,direction,kind,schema_json) VALUES(?,?,?,?,?,?,?)",
                      (project, p["id"], o["id"], p["name"], p["direction"], p.get("kind"), j(p.get("schema"))))
        for i in o.get("interfaces") or []:
            c.execute("INSERT INTO c4_interface(project,id,object_id,kind,name,signature,purpose,input,output,errors) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (project, i["id"], o["id"], i.get("kind"), i.get("name"), i.get("signature"), i.get("purpose"),
                       i.get("input"), i.get("output"), j(i.get("errors"))))
    for x in m["connections"]:
        c.execute("INSERT INTO c4_connection(id,project,from_id,to_id,name,technology,status,direction,tags,description,feature,interface,payload,kind,from_port_id,to_port_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (x["id"], project, x["from"], x["to"], x.get("name"), x.get("technology"), x.get("status"), x.get("direction"),
                   j(x.get("tags")), x.get("description"), x.get("feature"), x.get("interface"), j(x.get("payload")), x.get("kind"), x.get("from_port"), x.get("to_port")))
    for x in m["flows"]:
        c.execute("INSERT INTO c4_flow(id,project,name,steps) VALUES(?,?,?,?)", (x["id"], project, x.get("name"), j(x.get("steps") or [])))


def mutate_c4_object(c, role, project, op, object_id=None, fields=None, obj=None, parent=None):
    def mutate(m):
        objects = m["objects"]
        result = None
        if op == "create":
            if not isinstance(obj, dict): raise ValueError("object must be an object")
            bad = set(obj) - (C4_OBJECT_FIELDS | {"id"})
            if bad: raise ValueError(f"object field not editable: {sorted(bad)[0]}")
            if any(o["id"] == obj.get("id") for o in objects): raise ValueError("object id already exists")
            _validate_object(obj)
            objects.append(dict(obj)); target = obj.get("id")
        elif op in ("update", "move", "delete"):
            current = next((o for o in objects if o["id"] == object_id), None)
            if current is None: raise KeyError(f"no C4 object {object_id!r}")
            target = object_id
            if op == "delete":
                removed_links = {x["id"] for x in m["connections"] if object_id in (x["from"], x["to"])}
                removed_pairs = {(x["from"], x["to"]) for x in m["connections"] if x["id"] in removed_links}
                linked_refs = c.execute("SELECT count(*) FROM c4_link WHERE project=? AND object_id=?", (project, object_id)).fetchone()[0]
                objects.remove(current)
                m["connections"] = [x for x in m["connections"] if x["id"] not in removed_links]
                old_flows = len(m["flows"])
                m["flows"] = [f for f in m["flows"] if not any(
                    s.get("connection") in removed_links or (s.get("from"), s.get("to")) in removed_pairs
                    for s in f.get("steps", []))]
                removed_flows = old_flows - len(m["flows"])
                c.execute("DELETE FROM c4_link WHERE project=? AND object_id=?", (project, object_id))
                result = {"op": op, "id": object_id, "removed_connections": len(removed_links),
                          "removed_flows": removed_flows, "removed_item_links": linked_refs}
            elif op == "move": current["parent"] = parent
            else:
                if not isinstance(fields, dict) or not fields: raise ValueError("fields must be a non-empty object")
                bad = set(fields) - C4_OBJECT_FIELDS
                if bad: raise ValueError(f"field not editable: {sorted(bad)[0]}")
                before = {key: current.get(key) for key in fields}
                for key in ("type", "name"):
                    if key in fields: _required_text(fields[key], f"object {key}")
                if "parent" in fields and fields["parent"] is not None and not isinstance(fields["parent"], str):
                    raise ValueError("object parent must be a string or null")
                for key, value in fields.items():
                    if value is None: current.pop(key, None)
                    else: current[key] = value
                _validate_object(current)
                after = {key: current.get(key) for key in fields}
                result = {"op": op, "id": target}
                return result, f"c4_object:{target}", before, after
        else: raise ValueError("op must be create, update, move, or delete")
        return result or {"op": op, "id": target}, f"c4_object:{target}"
    return _c4_mutation(c, project, role, f"c4.object.{op}", mutate)


def mutate_c4_port(c, role, project, op, port_id=None, object_id=None, fields=None, port=None):
    def mutate(m):
        ports = [(o, p) for o in m["objects"] for p in o.get("ports", [])]
        found = next(((o, p) for o, p in ports if p["id"] == port_id), None)
        target_id = port_id
        if op == "create":
            if not isinstance(port, dict) or not isinstance(object_id, str): raise ValueError("object and port are required")
            bad = set(port) - (C4_PORT_FIELDS | {"id"})
            if bad: raise ValueError(f"port field not editable: {sorted(bad)[0]}")
            owner = next((o for o in m["objects"] if o["id"] == object_id), None)
            if owner is None: raise KeyError(f"no C4 object {object_id!r}")
            if any(p["id"] == port.get("id") for _, p in ports): raise ValueError("port id already exists")
            _validate_port(port)
            owner.setdefault("ports", []).append(dict(port)); target_id = port.get("id")
        elif found is None: raise KeyError(f"no C4 port {port_id!r}")
        elif op == "update":
            if not isinstance(fields, dict) or not fields: raise ValueError("fields must be a non-empty object")
            bad = set(fields) - C4_PORT_FIELDS
            if bad: raise ValueError(f"field not editable: {sorted(bad)[0]}")
            found[1].update(fields)
            _validate_port(found[1])
        elif op == "delete":
            found[0]["ports"].remove(found[1])
        else: raise ValueError("op must be create, update, or delete")
        return {"op": op, "id": target_id}, f"c4_port:{target_id}"
    return _c4_mutation(c, project, role, f"c4.port.{op}", mutate)


def mutate_c4_link(c, role, project, op, link_id=None, fields=None, link=None):
    def mutate(m):
        links = m["connections"]
        found = next((x for x in links if x["id"] == link_id), None)
        target_id = link_id
        if op == "create":
            if not isinstance(link, dict): raise ValueError("link must be an object")
            target_id = link.get("id")
            bad = set(link) - (C4_LINK_FIELDS | {"id"})
            if bad: raise ValueError(f"link field not editable: {sorted(bad)[0]}")
            if any(x["id"] == target_id for x in links): raise ValueError("link id already exists")
            _validate_link(link)
            links.append(dict(link))
        elif found is None: raise KeyError(f"no C4 link {link_id!r}")
        elif op == "update":
            if not isinstance(fields, dict) or not fields: raise ValueError("fields must be a non-empty object")
            bad = set(fields) - C4_LINK_FIELDS
            if bad: raise ValueError(f"field not editable: {sorted(bad)[0]}")
            found.update(fields)
            _validate_link(found)
        elif op == "delete": links.remove(found)
        else: raise ValueError("op must be create, update, or delete")
        return {"op": op, "id": target_id}, f"c4_connection:{target_id}"
    return _c4_mutation(c, project, role, f"c4.link.{op}", mutate)


def update_c4_object_fields(c, role, project, object_id, fields):
    if not isinstance(fields, dict) or not fields: raise ValueError("fields must be a non-empty object")
    if set(fields) - {"name", "description", "technology", "status"}: raise ValueError("field not editable")
    values = {}
    for key, value in fields.items():
        if not isinstance(value, str) or "\n" in value or "\r" in value: raise ValueError(f"{key} must be a single-line string")
        value = value.strip()
        if key == "name" and not value: raise ValueError("name is required")
        if key == "status" and value and value not in ("live", "future", "doing", "maintenance", "deprecated", "removed"): raise ValueError("status invalid")
        values[key] = value or None
    result = mutate_c4_object(c, role, project, "update", object_id, values)
    from strata import c4
    return next(o for o in c4.read_model(c, project)["objects"] if o["id"] == object_id)
