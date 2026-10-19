"""Write/read layer shared by CLI and MCP: role checks, audit on every write."""
import re
from strata import db

ROLES = ("main", "coder", "reviewer")


def _role(role):
    if role not in ROLES: raise PermissionError(f"unknown role {role!r}")


def add_item(c, role, project, kind, title, body=None, priority=None, status="open"):
    _role(role)
    if role != "main" and kind != "issue": raise PermissionError(f"{role} may only add issues")
    if role != "main": status = "open"
    return db.add_item(c, project, kind, title, body, priority, status, role)


def set_item(c, role, id, status=None, priority=None):
    _role(role)
    if role != "main":
        r = c.execute("SELECT kind FROM item WHERE id=?", (id,)).fetchone()
        if role == "reviewer" or priority is not None or (r and r["kind"] != "task"):
            raise PermissionError(f"{role} may only set status of a task")
        if status not in (None, "doing", "done"): raise PermissionError(f"{role} may only set status doing/done")
    db.set_item(c, id, status, priority, role)


def add_decision(c, role, project, title, context, decision, consequences, rejected, supersedes=None):
    _role(role)
    if not isinstance(rejected, str): raise ValueError("rejected must be a string")
    if rejected.strip() in ("", "[]"): raise ValueError("rejected options required")
    if supersedes is not None and role != "main": raise PermissionError(f"{role} may not supersede a decision")
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
    _role(role)
    if role != "main": raise PermissionError(f"{role} may not change decision status")
    r = c.execute("SELECT project,status FROM decision WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no decision {id}")
    c.execute("UPDATE decision SET status=? WHERE id=?", (status, id))  # CHECK rejects bad status
    db.audit(c, r["project"], "decision.set", f"decision:{id}", {"status": r["status"]}, {"status": status}, role)
    c.commit()


SRC_TABLE = {"item": "item", "decision": "decision", "page": "page", "doc": "doc"}


def search(c, q, project=None, src=None, limit=30, role="main"):
    """FTS5 over item/decision/page/doc. Terms are quoted (no FTS syntax from input), last one is a prefix."""
    _role(role)
    terms = re.findall(r"\w+", db.fold(q or ""))
    if not terms: raise ValueError("empty q")
    match = " ".join(f'"{t}"' for t in terms) + "*"
    sql, args = "SELECT src,ref,project,snippet(search,1,'','','…',12) snippet FROM search WHERE search MATCH ?", [match]
    if project: sql += " AND project=?"; args.append(project)
    if src: sql += " AND src=?"; args.append(src)
    args.append(max(1, min(int(limit), 100)))
    hits = [dict(r) for r in c.execute(sql + " ORDER BY bm25(search,10.0,1.0) LIMIT ?", args)]
    for h in hits:  # real title/key from the source row (the index holds the folded copy)
        col = {"item": "kind", "decision": "''", "page": "slug", "doc": "path"}[h["src"]]
        key = "id" if h["src"] in ("item", "decision") else "rowid"
        r = c.execute(f"SELECT title, {col} AS k FROM {SRC_TABLE[h['src']]} WHERE {key}=?", (h["ref"],)).fetchone()
        h["title"], h["key"] = (r["title"], r["k"]) if r else ("", "")
    return hits
