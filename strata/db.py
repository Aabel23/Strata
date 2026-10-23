import datetime, html.parser, json, os, pathlib, re, shutil, sqlite3, time

DEFAULT_DB = str(pathlib.Path(__file__).resolve().parent.parent / "strata.db")
SCHEMA = pathlib.Path(__file__).with_name("schema.sql")

def db_path(path=None):
    return str(path or os.environ.get("STRATA_DB") or DEFAULT_DB)

def connect(path=None):
    c = sqlite3.connect(db_path(path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")  # concurrent writers (MCP/CLI/server) wait instead of 'database is locked'
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def _item_rebuild_due(c):
    return not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone() and bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='item'").fetchone()) \
        and "spec" not in [r[1] for r in c.execute("PRAGMA table_info(item)")]

def _page_rebuild_due(c):
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='page'").fetchone()
    return bool(r) and "'plan'" not in r[0] and not c.execute("SELECT 1 FROM sqlite_master WHERE name='page_old'").fetchone()  # CHECK predates kind 'plan'

def _item_phase_due(c):
    cols = [r[1] for r in c.execute("PRAGMA table_info(item)")]
    return bool(cols) and not {"phase", "label"} <= set(cols)  # ALTER ADD COLUMN: back up first like the rebuilds

def _issue_kind_due(c):
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='item'").fetchone()
    return bool(r) and "'issue'" in r[0]  # CHECK predates label: issues are tasks labelled 'issue' (#203)

def _backup_if_rebuild(path):
    """Copy the DB file to <dir>/backups/strata-YYYYmmdd-HHMMSS.db before a destructive item/page rebuild (one backup for both) (before connect() flips it to WAL, so bytes match)."""
    p = db_path(path)
    if p == ":memory:" or not os.path.exists(p): return
    k = sqlite3.connect(p)
    try: due = _item_rebuild_due(k) or _page_rebuild_due(k) or _item_phase_due(k) or _issue_kind_due(k)
    finally: k.close()
    if due:
        d = pathlib.Path(p).parent / "backups"; d.mkdir(exist_ok=True)
        shutil.copy2(p, d / datetime.datetime.now().strftime("strata-%Y%m%d-%H%M%S.db"))

def _old_c4_due(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name IN ('c4_port','c4_interface')").fetchone())

def _backup_old_c4(path):
    """Before dropping the old single-file C4 format: backups/strata-pre-old-c4-drop-<timestamp>.db via the sqlite backup API."""
    p = db_path(path)
    if p == ":memory:" or not os.path.exists(p): return
    k = sqlite3.connect(p)
    try:
        if not _old_c4_due(k): return
        d = pathlib.Path(p).parent / "backups"; d.mkdir(exist_ok=True)
        dst = sqlite3.connect(d / datetime.datetime.now().strftime("strata-pre-old-c4-drop-%Y%m%d-%H%M%S.db"))
        try: k.backup(dst)
        finally: dst.close()
    finally: k.close()

def _drop_old_c4(c):
    """One-off: C4 rows of projects not imported as a layered folder, orphan c4_link rows, then tables c4_port/c4_interface
    (c4_connection is rebuilt first: its FKs point at c4_port). Layered = c4_meta.source is a folder, not a .yaml file."""
    if not _old_c4_due(c): return
    c.commit(); c.execute("PRAGMA foreign_keys=OFF")
    try:
        keep = "SELECT project FROM c4_meta WHERE source IS NOT NULL AND lower(source) NOT LIKE '%.yaml' AND lower(source) NOT LIKE '%.yml'"
        c.executescript(f"""BEGIN;
            DELETE FROM c4_link WHERE project NOT IN ({keep});
            DELETE FROM c4_connection WHERE project NOT IN ({keep});
            DELETE FROM c4_flow WHERE project NOT IN ({keep});
            DELETE FROM c4_contract WHERE project NOT IN ({keep});
            DELETE FROM c4_behavior WHERE project NOT IN ({keep});
            DELETE FROM c4_object WHERE project NOT IN ({keep});
            DELETE FROM c4_meta WHERE project NOT IN ({keep});
            DELETE FROM c4_link WHERE NOT EXISTS (SELECT 1 FROM c4_object o WHERE o.project=c4_link.project AND o.id=c4_link.object_id);
            CREATE TABLE c4_connection_new(
              id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
              name TEXT, status TEXT, description TEXT, detail TEXT, PRIMARY KEY(project,id));
            INSERT INTO c4_connection_new SELECT id,project,from_id,to_id,name,status,description,detail FROM c4_connection;
            DROP TABLE c4_connection; ALTER TABLE c4_connection_new RENAME TO c4_connection;
            DROP TABLE IF EXISTS c4_port; DROP TABLE IF EXISTS c4_interface;
            COMMIT;""")
    except BaseException:
        c.rollback(); raise
    finally: c.execute("PRAGMA foreign_keys=ON")

def init(path=None):
    _backup_if_rebuild(path)
    _backup_old_c4(path)
    c = connect(path)
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='research'").fetchone() and c.execute("SELECT 1 FROM research").fetchone():
        raise RuntimeError("table research is not empty: move rows to page(kind='research') first")
    rebuild = _migrate(c)
    items, pages = _item_rebuild_due(c), _page_rebuild_due(c)
    if items or pages:  # one transaction: rename + new schema + copy; any error rolls back to the old tables
        c.execute("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, so set it first
        try:
            c.executescript("BEGIN;" + ("DROP TRIGGER IF EXISTS item_ai;DROP TRIGGER IF EXISTS item_au;DROP TRIGGER IF EXISTS item_ad;"
                                        "ALTER TABLE item RENAME TO item_old;" if items else "")
                            + ("DROP TRIGGER IF EXISTS page_ai;DROP TRIGGER IF EXISTS page_au;DROP TRIGGER IF EXISTS page_ad;"
                               "ALTER TABLE page RENAME TO page_old;" if pages else "") + SCHEMA.read_text())
            _finish_item(c); _finish_page(c)
        except BaseException:
            c.rollback(); raise
        finally: c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA.read_text())
    _finish_item(c)
    _finish_page(c)
    _drop_issue_kind(c)
    if rebuild:  # copy rows from the old-CHECK table into the new one
        cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(c4_object_old)"))
        c.execute(f"INSERT INTO c4_object({cols}) SELECT {cols} FROM c4_object_old")
        c.execute("DROP TABLE c4_object_old")
    _drop_old_c4(c)
    c.commit()
    return c

def _finish_item(c):
    """Copy item_old into the rebuilt item table (old `scope` text becomes spec.scope), reindex, integrity-check."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone(): return
    cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(item_old)") if r["name"] != "scope")
    c.execute("DELETE FROM search WHERE src='item'")  # item_ai refills it row by row
    c.execute(f"INSERT INTO item({cols},spec) SELECT {cols}, CASE WHEN scope IS NULL THEN NULL "
              "WHEN json_valid(scope) THEN json_object('scope',json(scope)) ELSE json_object('scope',scope) END FROM item_old")
    c.execute("DROP TABLE item_old")
    if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")
    c.commit()

def _drop_issue_kind(c):
    """Issues become tasks with label 'issue' (open -> approved), then item is rebuilt without 'issue' in its kind CHECK
    (new table, same ids; item_dep keeps pointing at the name `item`). Idempotent."""
    if not _issue_kind_due(c): return
    c.commit()
    c.execute("UPDATE item SET label='issue', kind='task', status=CASE status WHEN 'open' THEN 'approved' ELSE status END WHERE kind='issue'")
    c.commit()
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS item\(.*?\);", SCHEMA.read_text(), re.S).group(0).replace("IF NOT EXISTS item(", "item_new(", 1)
    cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(item)"))
    c.execute("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, so set it first
    try:
        c.executescript(f"BEGIN;{ddl}INSERT INTO item_new({cols}) SELECT {cols} FROM item;DROP TABLE item;ALTER TABLE item_new RENAME TO item;COMMIT;")
        c.executescript(SCHEMA.read_text())  # index and FTS triggers died with the old table
        if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")
        if c.execute("PRAGMA foreign_key_check").fetchone(): raise RuntimeError("foreign_key_check failed after item rebuild")
    except BaseException:
        c.rollback(); raise
    finally: c.execute("PRAGMA foreign_keys=ON")

def _finish_page(c):
    """Copy page_old (CHECK predates kind 'plan') into the rebuilt page table keeping rowids, so FTS refs stay valid."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='page_old'").fetchone(): return
    cols = ",".join(r[1] for r in c.execute("PRAGMA table_info(page_old)"))
    c.execute("DELETE FROM search WHERE src='page'")  # page_ai refills it row by row
    c.execute(f"INSERT INTO page(rowid,{cols}) SELECT rowid,{cols} FROM page_old")
    c.execute("DROP TABLE page_old"); c.commit()
    if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")

# columns added after a table was first created: (table, column, type)
ADDED = [("c4_connection", "description", "TEXT"),
         ("c4_object", "kind", "TEXT"), ("c4_object", "owns", "JSON"), ("c4_object", "behavior", "TEXT"), ("c4_connection", "detail", "TEXT"),
         ("c4_object", "responsibilities", "JSON"), ("c4_object", "state", "TEXT"),
         ("item", "phase", "INT"), ("item", "roadmap", "TEXT"), ("item", "label", "TEXT"), ("doc", "prev_status", "TEXT"), ("doc", "summary", "TEXT"), ("doc", "code", "JSON"), ("c4_meta", "positions", "JSON"), ("c4_meta", "source", "TEXT")]

def _migrate(c):
    """ALTER old tables up to the current schema. Returns True if c4_object was renamed to c4_object_old
    (its type CHECK predates 'file'/'function' and SQLite cannot alter a CHECK) for init to copy back."""
    c.execute("DROP TABLE IF EXISTS object_layout")  # stored layout removed (#185): renderer lays out
    for t, col, typ in ADDED:
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})")]
        if cols and col not in cols: c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='decision'").fetchone():  # decisions removed (#211): drop table, triggers, index rows, links
        c.execute("DELETE FROM search WHERE src='decision'")
        for t in ("decision_ai", "decision_no_replace", "decision_no_delete", "decision_status_only"): c.execute(f"DROP TRIGGER IF EXISTS {t}")
        c.execute("DROP TABLE decision")
    l = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='c4_link'").fetchone()
    if l and "'decision'" in l["sql"]:  # SQLite cannot alter the old CHECK: rebuild with item rows only
        c.execute("CREATE TABLE c4_link_new(project TEXT NOT NULL, object_id TEXT NOT NULL, ref_kind TEXT NOT NULL CHECK(ref_kind IN ('item')), "
                  "ref_id INTEGER NOT NULL, PRIMARY KEY(project,object_id,ref_kind,ref_id))")
        c.execute("INSERT INTO c4_link_new SELECT project,object_id,ref_kind,ref_id FROM c4_link WHERE ref_kind='item'")
        c.execute("DROP TABLE c4_link"); c.execute("ALTER TABLE c4_link_new RENAME TO c4_link")
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='c4_object'").fetchone()
    if r and "'function'" not in r["sql"]:
        c.execute("ALTER TABLE c4_object RENAME TO c4_object_old"); return True
    return False

def fold(q):
    """Fold đ/Đ in an FTS query the same way the triggers fold indexed text."""
    return q.replace("đ", "d").replace("Đ", "D")


def put_page(c, project, slug, title, kind, blocks):
    """Insert or replace one page; `text` (for FTS) is derived from blocks."""
    from strata.blocks import page_text
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")
    existed = c.execute("SELECT 1 FROM page WHERE project=? AND slug=?", (project, slug)).fetchone()
    audit(c, project, "page.put", f"{project}/{slug}", after={"action": "update" if existed else "create"})  # never the body
    c.execute("INSERT INTO page(project,slug,title,kind,blocks,text,updated_at) VALUES(?,?,?,?,?,?,?) "
              "ON CONFLICT(project,slug) DO UPDATE SET title=excluded.title,kind=excluded.kind,"
              "blocks=excluded.blocks,text=excluded.text,updated_at=excluded.updated_at",
              (project, slug, title, kind, json.dumps(blocks, ensure_ascii=False), page_text(blocks), now))
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
