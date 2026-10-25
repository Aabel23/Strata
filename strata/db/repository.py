import datetime
import html.parser
import json
import os
import pathlib
import re
import sqlite3
import time

def fold(q):
    """Fold đ/Đ in an FTS query the same way the triggers fold indexed text."""
    return q.replace("đ", "d").replace("Đ", "D")

def put_page(c, project, slug, title, kind, blocks):
    """Insert or replace one page; `text` (for FTS) is derived from blocks."""
    from strata.blocks import page_text
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")
    existed = c.execute("SELECT 1 FROM page WHERE project=? AND slug=?", (project, slug)).fetchone()
    audit(c, project, "page.put", f"{project}/{slug}", after={"action": "update" if existed else "create"})  # never the body
    c.execute("INSERT INTO page(project,slug,title,kind,blocks,text,updated_at) VALUES(?,?,?,?,?,?,?) "
              "ON CONFLICT(project,slug) DO UPDATE SET title=excluded.title,kind=excluded.kind,"
              "blocks=excluded.blocks,text=excluded.text,updated_at=excluded.updated_at",
              (project, slug, title, kind, json.dumps(blocks, ensure_ascii=False), page_text(blocks), now_str))
    c.commit()

def get_page(c, project, slug):
    r = c.execute("SELECT project,slug,title,kind,blocks,updated_at FROM page WHERE project=? AND slug=?", (project, slug)).fetchone()
    return r and {**dict(r), "blocks": json.loads(r["blocks"])}

def list_pages(c, project=None):
    q = "SELECT project,slug,title,kind,updated_at FROM page" + (" WHERE project=?" if project else "") + " ORDER BY project,slug"
    return [dict(r) for r in c.execute(q, (project,) if project else ())]

# ---- project / doc / item writes (CLI only; every write leaves an audit row) ----
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")

def audit(c, project, tool, target, before=None, after=None, role="cli"):
    c.execute("INSERT INTO audit(project,actor_role,tool,target,before,after) VALUES(?,?,?,?,?,?)",
              (project, role, tool, target, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))

def add_project(c, id, name, root=None, docs_dir=None, parent=None, description=None):
    if docs_dir and root and not os.path.isabs(docs_dir): docs_dir = os.path.join(root, docs_dir)
    r = {"id": id, "name": name, "description": description, "root": root and os.path.abspath(root),
         "docs_dir": docs_dir and os.path.abspath(docs_dir), "parent": parent}
    c.execute("INSERT INTO project(id,name,description,root,docs_dir,parent) VALUES(:id,:name,:description,:root,:docs_dir,:parent)", r)
    audit(c, id, "project.add", id, None, r); c.commit()

def set_project(c, id, root=None, docs_dir=None, name=None, description=None):
    """Đổi root/docs_dir/name/description của project đã có; chỉ ghi trường được truyền."""
    old = c.execute("SELECT * FROM project WHERE id=?", (id,)).fetchone()
    if old is None: raise ValueError(f"không có project {id}")
    base = root or old["root"]
    if docs_dir and base and not os.path.isabs(docs_dir): docs_dir = os.path.join(base, docs_dir)
    new = {k: v for k, v in {"root": root and os.path.abspath(root), "docs_dir": docs_dir and os.path.abspath(docs_dir),
                             "name": name, "description": description}.items() if v is not None}
    if not new: raise ValueError("không có trường nào để đổi")
    c.execute(f"UPDATE project SET {', '.join(f'{k}=:{k}' for k in new)} WHERE id=:id", {**new, "id": id})
    audit(c, id, "project.set", id, {k: old[k] for k in new}, new); c.commit()

PROJECT_TABLES = ("item", "page", "doc", "c4_object", "c4_connection", "c4_meta", "c4_flow", "c4_contract", "c4_behavior", "c4_link")

def project_usage(c, id):
    """Rows a delete would remove, per table (non-empty only)."""
    out = {t: c.execute(f"SELECT count(*) FROM {t} WHERE project=?", (id,)).fetchone()[0] for t in PROJECT_TABLES}
    return {t: n for t, n in out.items() if n}

def backup(c):
    """Timestamped copy of the open DB into backups/ next to it (sqlite backup API); returns the path."""
    f = c.execute("PRAGMA database_list").fetchone()[2]
    if not f: raise ValueError("in-memory database cannot be backed up")
    d = os.path.join(os.path.dirname(os.path.abspath(f)), "backups"); os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 10**6:06d}-" + os.path.basename(f))
    out = sqlite3.connect(dst)
    try: c.backup(out)
    finally: out.close()
    return dst

def delete_project(c, id):
    """Remove the project and its rows (items, docs index, C4 model). Files on disk and the audit trail stay."""
    old = c.execute("SELECT * FROM project WHERE id=?", (id,)).fetchone()
    if old is None: raise KeyError(f"no project {id}")
    kids = [r[0] for r in c.execute("SELECT id FROM project WHERE parent=?", (id,))]
    if kids: raise ValueError(f"project {id} has sub-projects ({', '.join(kids)}); delete or move them first")
    gone = project_usage(c, id)
    try:
        for t in PROJECT_TABLES: c.execute(f"DELETE FROM {t} WHERE project=?", (id,))
        c.execute("DELETE FROM project WHERE id=?", (id,))
        audit(c, id, "project.delete", id, {k: old[k] for k in old.keys()}, {"removed": gone}, "main")
        c.commit()
    except BaseException: c.rollback(); raise

# issues first, then priority (high, medium, low/none), then id; service.py list/ready should ORDER BY this
ITEM_ORDER = ("(label IS NOT 'issue'), CASE lower(coalesce(priority,'')) WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'high' THEN 1 "
              "WHEN 'p2' THEN 2 WHEN 'medium' THEN 2 WHEN 'p3' THEN 3 WHEN 'low' THEN 3 ELSE 9 END, id")

def add_item(c, project, kind, title, body=None, priority=None, status="open", role="cli", spec=None, label=None):
    if kind == "issue": kind, label = "task", label or "issue"  # alias kept for old callers
    if not c.execute("SELECT 1 FROM project WHERE id=?", (project,)).fetchone(): raise KeyError(f"no project {project}")
    t = now()
    cur = c.execute("INSERT INTO item(project,kind,title,body,status,priority,spec,created_by,created_at,updated_at,label) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (project, kind, title, body, status, priority, None if spec is None else json.dumps(spec, ensure_ascii=False), role, t, t, label))
    audit(c, project, "item.add", f"item:{cur.lastrowid}", None, {"kind": kind, "title": title, "status": status, **({"label": label} if label else {})}, role)
    c.commit(); return cur.lastrowid

def set_item(c, id, status=None, priority=None, role="cli"):
    r = c.execute("SELECT project,status,priority FROM item WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no item {id}")
    new = {"status": status or r["status"], "priority": priority if priority is not None else r["priority"]}
    c.execute("UPDATE item SET status=?,priority=?,updated_at=?,version=version+1 WHERE id=?", (new["status"], new["priority"], now(), id))
    audit(c, r["project"], "item.set", f"item:{id}", {"status": r["status"], "priority": r["priority"]}, new, role); c.commit()

class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.title = self.h1 = None; self.skip = 0; self.cur = None
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skip += 1
        if tag in ("title", "h1") and getattr(self, tag) is None: self.cur = tag; setattr(self, tag, "")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip: self.skip -= 1
        if tag == self.cur: self.cur = None
    def handle_data(self, d):
        if self.skip: return
        if self.cur: setattr(self, self.cur, getattr(self, self.cur) + d)
        if self.cur != "title": self.out.append(d)

def doc_files(base):
    """*.html and *.md under base, skipping assets/, plan/archive/ and dot paths."""
    for f in sorted([*base.rglob("*.yaml"), *base.rglob("*.html"), *base.rglob("*.md")]):
        parts = f.relative_to(base).parts
        if any(x.startswith(".") for x in parts) or parts[0] == "assets" or parts[:2] == ("plan", "archive"): continue
        yield f

def docs_stamp(base):
    """Cheap fingerprint of docs_dir: changes when a doc is added, removed or edited."""
    return tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in doc_files(base))

def scan_docs(c, project, audit_row=True):
    """Walk docs_dir for *.yaml (the default doc format), *.html and *.md; upsert changed docs, mark vanished ones missing. Returns (found, missing)."""
    r = c.execute("SELECT docs_dir FROM project WHERE id=?", (project,)).fetchone()
    if not r or not r["docs_dir"] or not os.path.isdir(r["docs_dir"]): raise ValueError(f"project {project}: docs_dir not set or not a directory")
    base = pathlib.Path(r["docs_dir"]); seen = set(); changed = 0
    for f in doc_files(base):
        rel = f.relative_to(base); parts = rel.parts
        src = f.read_text(encoding="utf-8", errors="replace")
        summary = None; code = None
        if f.suffix == ".yaml":
            from strata.blocks import load_doc, page_text
            d, _ = load_doc(src)
            title = d["title"] if isinstance(d["title"], str) and d["title"] else rel.stem
            summary = d["summary"] if isinstance(d["summary"], str) else None
            code = d["code"] if all(isinstance(x, str) for x in d["code"]) else []  # metadata only; the TOC groups by folder
            text = " ".join(" ".join(filter(None, [summary, page_text(d["blocks"])])).split())
        elif f.suffix == ".md":
            h = re.search(r"^# +(.+)$", src, re.M); title = h[1].strip() if h else rel.stem; text = " ".join(src.split())
        else:
            p = _Text(); p.feed(src)
            text = " ".join(" ".join(p.out).split())
            title = (p.title or p.h1 or rel.stem).strip() or rel.stem
        kind = parts[0] if len(parts) > 1 and parts[0] in ("research", "architect", "review", "plan") else "other"
        path = rel.as_posix(); seen.add(path)
        cj = json.dumps(code, ensure_ascii=False) if code is not None else None
        old = c.execute("SELECT title,kind,text,status,summary,code FROM doc WHERE project=? AND path=?", (project, path)).fetchone()
        if old and (old["title"], old["kind"], old["text"], old["summary"], old["code"]) == (title, kind, text, summary, cj) and old["status"] != "missing": continue
        changed += 1
        c.execute("INSERT INTO doc(project,path,title,kind,text,updated_at,summary,code) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project,path) DO UPDATE SET "
                  "title=excluded.title,kind=excluded.kind,text=excluded.text,updated_at=excluded.updated_at,summary=excluded.summary,code=excluded.code,"
                  "status=CASE WHEN doc.status='missing' THEN coalesce(doc.prev_status,'current') ELSE doc.status END,"
                  "prev_status=CASE WHEN doc.status='missing' THEN NULL ELSE doc.prev_status END", (project, path, title, kind, text, now(), summary, cj))
    gone = [x["path"] for x in c.execute("SELECT path FROM doc WHERE project=? AND status!='missing'", (project,)) if x["path"] not in seen]
    for path in gone: c.execute("UPDATE doc SET prev_status=status,status='missing',updated_at=? WHERE project=? AND path=?", (now(), project, path))
    if audit_row and (changed or gone): audit(c, project, "doc.scan", project, None, {"found": len(seen), "changed": changed, "missing": len(gone)})
    c.commit()
    return len(seen), len(gone)

def set_doc(c, project, path, feature=None, status=None, ord=None):
    r = c.execute("SELECT feature,status,ord FROM doc WHERE project=? AND path=?", (project, path)).fetchone()
    if not r: raise KeyError(f"no doc {project}/{path}")
    new = {"feature": feature if feature is not None else r["feature"], "status": status or r["status"], "ord": r["ord"] if ord is None else ord}
    c.execute("UPDATE doc SET feature=?,status=?,ord=? WHERE project=? AND path=?", (new["feature"], new["status"], new["ord"], project, path))
    audit(c, project, "doc.set", f"doc:{path}", dict(r), new); c.commit()

# ---- C4 object <-> item links ----
def _link_target(c, project, object, item, decision, must_exist=True):
    if decision is not None or item is None: raise ValueError("give --item")
    if must_exist and not c.execute("SELECT 1 FROM c4_object WHERE project=? AND id=?", (project, object)).fetchone():
        raise ValueError(f"no object {project}/{object}")
    if not c.execute("SELECT 1 FROM item WHERE project=? AND id=?", (project, item)).fetchone():
        raise ValueError(f"no item {item} in project {project}")
    return "item", item

def link(c, project, object, item=None, decision=None):
    """Returns True if added, False if it already existed (no audit then). `decision` stays only so old callers get a clean ValueError."""
    kind, rid = _link_target(c, project, object, item, decision)
    if not c.execute("INSERT OR IGNORE INTO c4_link VALUES(?,?,?,?)", (project, object, kind, rid)).rowcount: return False
    audit(c, project, "c4.link", f"{object}->{kind}:{rid}", None, {"object": object, "ref_kind": kind, "ref_id": rid}); c.commit()
    return True

def unlink(c, project, object, item=None, decision=None):
    kind, rid = _link_target(c, project, object, item, decision, must_exist=False)  # an object removed by re-import must stay unlinkable
    if not c.execute("DELETE FROM c4_link WHERE project=? AND object_id=? AND ref_kind=? AND ref_id=?", (project, object, kind, rid)).rowcount: return False
    audit(c, project, "c4.unlink", f"{object}->{kind}:{rid}", {"object": object, "ref_kind": kind, "ref_id": rid}, None); c.commit()
    return True

def links_for(c, project, object=None):
    """{items:[{id,kind,title,status}]} for one object; for object=None, {object_id: that} for the whole project."""
    out = {}
    for r in c.execute("SELECT l.object_id oid,t.id,t.kind,t.title,t.status FROM c4_link l JOIN item t ON t.id=l.ref_id "
                       "WHERE l.project=? AND t.project=? " + ("AND l.object_id=? " if object else "") + "ORDER BY t.id",
                       (project, project, *([object] if object else []))):
        d = dict(r); out.setdefault(d.pop("oid"), {"items": []})["items"].append(d)
    return out.get(object, {"items": []}) if object else out


# ---- Project queries ----
def get_project(c, id):
    """Return dict or None for SELECT * FROM project WHERE id=?"""
    r = c.execute("SELECT * FROM project WHERE id=?", (id,)).fetchone()
    return dict(r) if r else None


def project_exists(c, id):
    """Return bool SELECT 1 FROM project WHERE id=?"""
    return c.execute("SELECT 1 FROM project WHERE id=?", (id,)).fetchone() is not None


def get_project_parent(c, id):
    """Return parent id or None SELECT parent FROM project WHERE id=?"""
    r = c.execute("SELECT parent FROM project WHERE id=?", (id,)).fetchone()
    return r[0] if r else None


def get_project_root_or_c4_root(c, project_id):
    """Return root string from SELECT coalesce(p.root, m.root) FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?"""
    r = c.execute("SELECT coalesce(p.root, m.root) FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (project_id,)).fetchone()
    return r[0] if r else None


def project_for_path(c, path):
    """Id of the project whose root is `path` or its deepest ancestor (realpath compare), else None."""
    import os
    path, best = os.path.realpath(path), (0, None)
    for pid, root in c.execute("SELECT id, root FROM project WHERE root IS NOT NULL AND root != ''"):
        r = os.path.realpath(root)
        if (path == r or path.startswith(r.rstrip("/") + "/")) and len(r) > best[0]: best = (len(r), pid)
    return best[1]


def list_projects_with_docs(c):
    """Return list of rows/dicts SELECT id,docs_dir FROM project WHERE docs_dir IS NOT NULL"""
    return [dict(r) for r in c.execute("SELECT id,docs_dir FROM project WHERE docs_dir IS NOT NULL")]


# ---- Item queries & updates ----
def get_item(c, id):
    """Return Row/dict or None for SELECT * FROM item WHERE id=?"""
    r = c.execute("SELECT * FROM item WHERE id=?", (id,)).fetchone()
    return dict(r) if r else None


def get_item_project(c, id):
    """Return dict with project, version or None"""
    r = c.execute("SELECT project,version FROM item WHERE id=?", (id,)).fetchone()
    return dict(r) if r else None


def get_item_deps(c, id, kind="depends_on"):
    """Returns dependency info for item id (kind='depends_on' or 'blocks')."""
    if kind == "blocks":
        sql = "SELECT i.id,i.title,i.status FROM item_dep d JOIN item i ON i.id=d.item_id WHERE d.depends_on=? ORDER BY i.id"
    else:
        sql = "SELECT i.id,i.title,i.status FROM item_dep d JOIN item i ON i.id=d.depends_on WHERE d.item_id=? ORDER BY i.id"
    return [dict(x) for x in c.execute(sql, (id,))]


def get_undone_deps(c, id):
    """List of depends_on ids where status != 'done'"""
    return [x[0] for x in c.execute("SELECT depends_on FROM item_dep d JOIN item i ON i.id=d.depends_on WHERE d.item_id=? AND i.status!='done'", (id,))]


def get_item_last_audit_version(c, id, status="review"):
    """Get audit transition version check (default status='review')."""
    target = id if str(id).startswith("item:") else f"item:{id}"
    r = c.execute("SELECT json_extract(after,'$.version') FROM audit WHERE target=? AND tool='item.transition' AND json_extract(after,'$.status')=? ORDER BY id DESC LIMIT 1", (target, status)).fetchone()
    return r[0] if r else None


def update_item_transition(c, id, from_status, to_status, owner, claimed_at, version):
    cur = c.execute(
        "UPDATE item SET status=?,owner=?,claimed_at=?,updated_at=?,version=version+1 WHERE id=? AND status=? AND version=?",
        (to_status, owner, claimed_at, now(), id, from_status, version)
    )
    return cur.rowcount


def update_item_fields(c, id, version, fields):
    if not fields:
        return 0
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    sets = ", ".join(f"{k}=?" for k in fields.keys())
    cur = c.execute(f"UPDATE item SET {sets},updated_at=?,version=version+1 WHERE id=? AND version=?", (*vals, now(), id, version))
    return cur.rowcount


def delete_item_cascade(c, id, project):
    deps = [[x[0], x[1]] for x in c.execute("SELECT item_id,depends_on FROM item_dep WHERE item_id=? OR depends_on=?", (id, id))]
    links = c.execute("DELETE FROM c4_link WHERE project=? AND ref_kind='item' AND ref_id=?", (project, id)).rowcount
    c.execute("DELETE FROM item_dep WHERE item_id=? OR depends_on=?", (id, id))
    c.execute("DELETE FROM item WHERE id=?", (id,))
    return {"deps": deps, "c4_links": links}


def remove_item_dep(c, id, depends_on):
    return c.execute("DELETE FROM item_dep WHERE item_id=? AND depends_on=?", (id, depends_on)).rowcount


def add_item_dep(c, id, depends_on):
    return c.execute("INSERT OR IGNORE INTO item_dep VALUES(?,?)", (id, depends_on)).rowcount


def list_items(c, where_clauses=None, args=None, order_by=None):
    sql = "SELECT * FROM item"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    ob = ITEM_ORDER if order_by is None else order_by
    if ob:
        sql += f" ORDER BY {ob}"
    return [dict(r) for r in c.execute(sql, tuple(args or ()))]


def get_item_c4_objects(c, project, item_id):
    return [r[0] for r in c.execute("SELECT object_id FROM c4_link WHERE project=? AND ref_kind='item' AND ref_id=? ORDER BY object_id", (project, item_id))]


def get_item_audit(c, item_id):
    target = item_id if str(item_id).startswith("item:") else f"item:{item_id}"
    return [dict(r) for r in c.execute("SELECT ts,actor_role,tool,before,after FROM audit WHERE target=? ORDER BY id DESC", (target,))]


def get_open_issues_objects(c, project):
    return [r[0] for r in c.execute("SELECT DISTINCT l.object_id FROM c4_link l JOIN item i ON i.id=l.ref_id AND l.ref_kind='item' WHERE l.project=? AND i.status IN ('open','doing','approved') ORDER BY l.object_id", (project,))]


# ---- Search and Pragma ----
def search_fts(c, terms, project=None, limit=20):
    if isinstance(terms, str):
        term_list = re.findall(r"\w+", fold(terms))
    else:
        term_list = [w for t in terms for w in (re.findall(r"\w+", fold(str(t))) or [fold(str(t))]) if w]
    if not term_list:
        return []
    match = " ".join(f'"{t}"' for t in term_list) + "*"
    sql = "SELECT src,ref,project,snippet(search,1,'','','…',12) snippet FROM search WHERE search MATCH ?"
    args = [match]
    if project:
        sql += " AND project=?"
        args.append(project)
    sql += " ORDER BY bm25(search,10.0,1.0) LIMIT ?"
    args.append(limit)
    return [dict(r) for r in c.execute(sql, args)]


def get_data_version(c):
    r = c.execute("PRAGMA data_version").fetchone()
    return int(r[0]) if r else 0


def query_rows(c, sql, args=()):
    cur = c.execute(sql, args)
    rows = c.fetchall() if hasattr(c, "fetchall") else cur.fetchall()
    return [dict(r) for r in rows]


