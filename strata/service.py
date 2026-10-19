"""Write/read layer shared by CLI and MCP: role checks, audit on every write."""
import re
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


def add_item(c, role, project, kind, title, body=None, priority=None, status="open"):
    info = {"kind": kind, "title": title}
    _role(c, role, "item.add", project, None, info)
    if role != "main" and kind != "issue": _deny(c, role, "item.add", project, None, info, f"{role} may only add issues")
    if role != "main": status = "open"
    return db.add_item(c, project, kind, title, body, priority, status, role)


def set_item(c, role, id, status=None, priority=None):
    r = c.execute("SELECT kind,project FROM item WHERE id=?", (id,)).fetchone()
    d = lambda msg: _deny(c, role, "item.set", r and r["project"], f"item:{id}", {"id": id, "status": status, "priority": priority}, msg)
    if role not in ROLES: d(f"unknown role {role!r}")
    if role != "main":
        if role == "reviewer" or priority is not None or (r and r["kind"] != "task"): d(f"{role} may only set status of a task")
        if status not in (None, "doing", "done"): d(f"{role} may only set status doing/done")
    db.set_item(c, id, status, priority, role)


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
