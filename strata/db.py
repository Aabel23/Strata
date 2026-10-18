import datetime, html.parser, json, os, pathlib, sqlite3

DEFAULT_DB = "/home/abel/.secondbrain/strata.db"
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
    cols = [r["name"] for r in c.execute("PRAGMA table_info(c4_connection)")]
    if cols and "description" not in cols:  # DB created before T2
        c.execute("ALTER TABLE c4_connection ADD COLUMN description TEXT")
    c.executescript(SCHEMA.read_text())
    c.commit()
    return c

def fold(q):
    """Fold đ/Đ in an FTS query the same way the triggers fold indexed text."""
    return q.replace("đ", "d").replace("Đ", "D")


def put_page(c, project, slug, title, kind, blocks):
    """Insert or replace one page; `text` (for FTS) is derived from blocks."""
    from strata.blocks import page_text
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")
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

def audit(c, project, tool, target, before=None, after=None):
    c.execute("INSERT INTO audit(project,actor_role,tool,target,before,after) VALUES(?,?,?,?,?,?)",
              (project, "cli", tool, target, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))

def add_project(c, id, name, root=None, docs_dir=None, parent=None, description=None):
    if docs_dir and root and not os.path.isabs(docs_dir): docs_dir = os.path.join(root, docs_dir)
    r = {"id": id, "name": name, "description": description, "root": root and os.path.abspath(root),
         "docs_dir": docs_dir and os.path.abspath(docs_dir), "parent": parent}
    c.execute("INSERT INTO project(id,name,description,root,docs_dir,parent) VALUES(:id,:name,:description,:root,:docs_dir,:parent)", r)
    audit(c, id, "project.add", id, None, r); c.commit()

def add_item(c, project, kind, title, body=None, priority=None, status="open"):
    t = now()
    cur = c.execute("INSERT INTO item(project,kind,title,body,status,priority,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'cli',?,?)",
                    (project, kind, title, body, status, priority, t, t))
    audit(c, project, "item.add", f"item:{cur.lastrowid}", None, {"kind": kind, "title": title, "status": status})
    c.commit(); return cur.lastrowid

def set_item(c, id, status=None, priority=None):
    r = c.execute("SELECT project,status,priority FROM item WHERE id=?", (id,)).fetchone()
    if not r: raise KeyError(f"no item {id}")
    new = {"status": status or r["status"], "priority": priority if priority is not None else r["priority"]}
    c.execute("UPDATE item SET status=?,priority=?,updated_at=?,version=version+1 WHERE id=?", (new["status"], new["priority"], now(), id))
    audit(c, r["project"], "item.set", f"item:{id}", {"status": r["status"], "priority": r["priority"]}, new); c.commit()

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

def scan_docs(c, project):
    """Walk docs_dir for *.html; upsert changed docs, mark vanished ones missing. Returns (found, missing)."""
    r = c.execute("SELECT docs_dir FROM project WHERE id=?", (project,)).fetchone()
    if not r or not r["docs_dir"] or not os.path.isdir(r["docs_dir"]): raise ValueError(f"project {project}: docs_dir not set or not a directory")
    base = pathlib.Path(r["docs_dir"]); seen = set()
    for f in sorted(base.rglob("*.html")):
        rel = f.relative_to(base); parts = rel.parts
        if any(x.startswith(".") for x in parts[:-1]) or parts[0] == "assets" or parts[:2] == ("plan", "archive") or f.name.startswith("."): continue
        p = _Text(); p.feed(f.read_text(encoding="utf-8", errors="replace"))
        text = " ".join(" ".join(p.out).split())
        title = (p.title or p.h1 or rel.stem).strip() or rel.stem
        kind = parts[0] if len(parts) > 1 and parts[0] in ("research", "architect", "review", "plan") else "other"
        path = rel.as_posix(); seen.add(path)
        old = c.execute("SELECT title,kind,text,status FROM doc WHERE project=? AND path=?", (project, path)).fetchone()
        if old and (old["title"], old["kind"], old["text"]) == (title, kind, text) and old["status"] != "missing": continue
        c.execute("INSERT INTO doc(project,path,title,kind,text,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(project,path) DO UPDATE SET "
                  "title=excluded.title,kind=excluded.kind,text=excluded.text,updated_at=excluded.updated_at,"
                  "status=CASE WHEN doc.status='missing' THEN 'current' ELSE doc.status END", (project, path, title, kind, text, now()))
    gone = [x["path"] for x in c.execute("SELECT path FROM doc WHERE project=? AND status!='missing'", (project,)) if x["path"] not in seen]
    for path in gone: c.execute("UPDATE doc SET status='missing',updated_at=? WHERE project=? AND path=?", (now(), project, path))
    audit(c, project, "doc.scan", project, None, {"found": len(seen), "missing": len(gone)}); c.commit()
    return len(seen), len(gone)

def set_doc(c, project, path, feature=None, status=None, ord=None):
    r = c.execute("SELECT feature,status,ord FROM doc WHERE project=? AND path=?", (project, path)).fetchone()
    if not r: raise KeyError(f"no doc {project}/{path}")
    new = {"feature": feature if feature is not None else r["feature"], "status": status or r["status"], "ord": r["ord"] if ord is None else ord}
    c.execute("UPDATE doc SET feature=?,status=?,ord=? WHERE project=? AND path=?", (new["feature"], new["status"], new["ord"], project, path))
    audit(c, project, "doc.set", f"doc:{path}", dict(r), new); c.commit()
