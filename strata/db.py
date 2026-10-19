import datetime, html.parser, json, os, pathlib, re, sqlite3

DEFAULT_DB = str(pathlib.Path(__file__).resolve().parent.parent / "strata.db")
SCHEMA = pathlib.Path(__file__).with_name("schema.sql")

def db_path(path=None):
    return str(path or os.environ.get("STRATA_DB") or DEFAULT_DB)

def connect(path=None):
    c = sqlite3.connect(db_path(path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init(path=None):
    c = connect(path)
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='research'").fetchone() and c.execute("SELECT 1 FROM research").fetchone():
        raise RuntimeError("table research is not empty: move rows to page(kind='research') first")
    rebuild = _migrate(c)
    c.executescript(SCHEMA.read_text())
    _finish_item(c)
    if rebuild:  # copy rows from the old-CHECK table into the new one
        cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(c4_object_old)"))
        c.execute(f"INSERT INTO c4_object({cols}) SELECT {cols} FROM c4_object_old")
        c.execute("DROP TABLE c4_object_old")
    c.commit()
    return c

def _finish_item(c):
    """Copy item_old into the rebuilt item table (old `scope` text becomes spec.scope), reindex, integrity-check."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone(): return
    cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(item_old)") if r["name"] != "scope")
    c.execute("DELETE FROM search WHERE src='item'")  # item_ai refills it row by row
    c.execute(f"INSERT INTO item({cols},spec) SELECT {cols}, CASE WHEN scope IS NULL THEN NULL "
              "WHEN json_valid(scope) THEN json_object('scope',json(scope)) ELSE json_object('scope',scope) END FROM item_old")
    c.execute("DROP TABLE item_old"); c.commit()
    c.execute("PRAGMA foreign_keys=ON")
    if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")

# columns added after a table was first created: (table, column, type)
ADDED = [("c4_connection", "description", "TEXT"), ("c4_connection", "feature", "TEXT"), ("c4_connection", "interface", "TEXT"),
         ("c4_connection", "payload", "JSON"), ("c4_connection", "kind", "TEXT"),
         ("c4_object", "responsibilities", "JSON"), ("c4_object", "state", "TEXT"),
         ("doc", "prev_status", "TEXT"), ("doc", "summary", "TEXT"), ("doc", "code", "JSON")]

def _migrate(c):
    """ALTER old tables up to the current schema. Returns True if c4_object was renamed to c4_object_old
    (its type CHECK predates 'file'/'function' and SQLite cannot alter a CHECK) for init to copy back."""
    for t, col, typ in ADDED:
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})")]
        if cols and col not in cols: c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    t = c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='decision_ai'").fetchone()
    if t and "rejected_options" not in t["sql"]:  # old index body lacks rejected options: schema.sql recreates the trigger, reindex here
        c.execute("DROP TRIGGER decision_ai"); c.execute("DELETE FROM search WHERE src='decision'")
        c.execute("INSERT INTO search SELECT replace(replace(title,'đ','d'),'Đ','D'), replace(replace(trim(coalesce(context,'')||' '||coalesce(decision,'')||' '||coalesce(consequences,'')||' '||coalesce(rejected_options,'')),'đ','d'),'Đ','D'), 'decision', id, project FROM decision")
    if "spec" not in [r["name"] for r in c.execute("PRAGMA table_info(item)")] and c.execute("SELECT 1 FROM sqlite_master WHERE name='item'").fetchone():
        c.commit(); c.execute("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, hence the commit
        for t in ("item_ai", "item_au", "item_ad"): c.execute(f"DROP TRIGGER IF EXISTS {t}")
        c.execute("ALTER TABLE item RENAME TO item_old")  # init's schema script makes the new table, _finish_item copies
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

def add_item(c, project, kind, title, body=None, priority=None, status="open", role="cli", spec=None):
    if not c.execute("SELECT 1 FROM project WHERE id=?", (project,)).fetchone(): raise KeyError(f"no project {project}")
    t = now()
    cur = c.execute("INSERT INTO item(project,kind,title,body,status,priority,spec,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (project, kind, title, body, status, priority, None if spec is None else json.dumps(spec, ensure_ascii=False), role, t, t))
    audit(c, project, "item.add", f"item:{cur.lastrowid}", None, {"kind": kind, "title": title, "status": status}, role)
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


# ---- C4 object <-> item/decision links ----
def _link_target(c, project, object, item, decision):
    if (item is None) == (decision is None): raise ValueError("give exactly one of --item / --decision")
    if not c.execute("SELECT 1 FROM c4_object WHERE project=? AND id=?", (project, object)).fetchone():
        raise ValueError(f"no object {project}/{object}")
    kind, rid = ("item", item) if item is not None else ("decision", decision)
    if not c.execute(f"SELECT 1 FROM {kind} WHERE project=? AND id=?", (project, rid)).fetchone():
        raise ValueError(f"no {kind} {rid} in project {project}")
    return kind, rid

def link(c, project, object, item=None, decision=None):
    """Returns True if added, False if it already existed (no audit then)."""
    kind, rid = _link_target(c, project, object, item, decision)
    if not c.execute("INSERT OR IGNORE INTO c4_link VALUES(?,?,?,?)", (project, object, kind, rid)).rowcount: return False
    audit(c, project, "c4.link", f"{object}->{kind}:{rid}", None, {"object": object, "ref_kind": kind, "ref_id": rid}); c.commit()
    return True

def unlink(c, project, object, item=None, decision=None):
    kind, rid = _link_target(c, project, object, item, decision)
    if not c.execute("DELETE FROM c4_link WHERE project=? AND object_id=? AND ref_kind=? AND ref_id=?", (project, object, kind, rid)).rowcount: return False
    audit(c, project, "c4.unlink", f"{object}->{kind}:{rid}", {"object": object, "ref_kind": kind, "ref_id": rid}, None); c.commit()
    return True

def links_for(c, project, object=None):
    """{items:[{id,kind,title,status}], decisions:[{id,title,status}]} for one object; for object=None, {object_id: that} for the whole project."""
    out = {}
    for kind, cols in (("item", "t.id,t.kind,t.title,t.status"), ("decision", "t.id,t.title,t.status")):
        for r in c.execute(f"SELECT l.object_id oid,{cols} FROM c4_link l JOIN {kind} t ON t.id=l.ref_id "
                           f"WHERE l.project=? AND l.ref_kind='{kind}' AND t.project=? "
                           + ("AND l.object_id=? " if object else "") + "ORDER BY t.id", (project, project, *([object] if object else []))):
            d = dict(r); o = out.setdefault(d.pop("oid"), {"items": [], "decisions": []})
            o["items" if kind == "item" else "decisions"].append(d)
    return out.get(object, {"items": [], "decisions": []}) if object else out
