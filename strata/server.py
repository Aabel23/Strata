"""HTTP server: C4 viewer, pages and their JSON APIs. All data comes from the DB."""
import http.server, json, mimetypes, pathlib, re, sqlite3, threading
from urllib.parse import parse_qs, unquote, urlsplit
from strata import blocks, c4, db

VIEWER = pathlib.Path(__file__).resolve().parent.parent / "viewer"
STATIC = {"/": "app.html", "/app.js": "app.js", "/app.css": "app.css", "/c4": "index.html", "/index.html": "index.html", "/page.js": "page.js", "/page.css": "page.css"}
TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".json": "application/json"}
SHOW = {"item": "id,project,kind,title,status,priority,owner", "decision": "id,project,title,status"}
ITEM_KINDS = ("rule", "task", "issue", "knowledge", "draft", "note")
ITEM_STATUS = ("proposed", "approved", "open", "doing", "done", "rejected")
CLOSED = "('done','rejected')"
SRC_TABLE = {"item": "item", "decision": "decision", "page": "page", "doc": "doc"}


def make_server(db_path=None, project=None, port=0):
    db.init(db_path).close()
    conn = sqlite3.connect(db.db_path(db_path), check_same_thread=False)  # one long-lived conn: data_version needs it
    conn.row_factory = sqlite3.Row
    lock = threading.RLock()

    def rows(sql, args=()):
        with lock: return [dict(r) for r in conn.execute(sql, args)]

    def default_project():
        ps = rows("SELECT project FROM c4_meta")
        return project or (ps[0]["project"] if len(ps) == 1 else None)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self.send_error(403)  # DNS rebinding guard
            u = urlsplit(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            parts = [unquote(x) for x in u.path.split("/")]  # ['', 'api', ...]
            p = u.path
            if p in STATIC: return self.file(VIEWER / STATIC[p])
            if p == "/api/projects": return self.json(self.projects())
            if p == "/api/items": return self.items(q)
            if p == "/api/decisions":
                return self.json(rows("SELECT * FROM decision" + (" WHERE project=?" if q.get("project") else "") + " ORDER BY id DESC", (q["project"],) if q.get("project") else ()))
            if p == "/api/docs":
                return self.json(rows("SELECT project,path,title,feature,kind,status,ord,updated_at FROM doc" + (" WHERE project=?" if q.get("project") else "")
                                      + " ORDER BY project,ord,path", (q["project"],) if q.get("project") else ()))
            if p == "/api/audit": return self.audit(q)
            if p == "/api/search": return self.search(q)
            if parts[1:2] == ["docs"] and len(parts) > 3:
                with lock: r = rows("SELECT docs_dir FROM project WHERE id=?", (parts[2],))
                segs = parts[3:]
                hidden = any(x.startswith(".") for x in segs) or segs[-1].endswith(".db") or ".sqlite" in segs[-1]
                if r and r[0]["docs_dir"] and not hidden:
                    try:
                        root = pathlib.Path(r[0]["docs_dir"]).resolve(); f = (root / "/".join(segs)).resolve()
                        if f.is_relative_to(root) and f.is_file(): return self.file(f)
                    except (ValueError, OSError): pass
                return self.send_error(404)
            if p == "/pages": return self.file(VIEWER / "page.html")
            if parts[1:2] == ["page"] and len(parts) == 4:
                with lock: ok = db.get_page(conn, parts[2], parts[3])
                return self.file(VIEWER / "page.html") if ok else self.send_error(404)
            if p == "/api/c4":
                proj = q.get("project") or default_project()
                with lock:
                    m = c4.read_model(conn, proj)
                    links = db.links_for(conn, proj) if m else {}
                    open_issues = [r["object_id"] for r in conn.execute(
                        "SELECT DISTINCT l.object_id FROM c4_link l JOIN item t ON t.id=l.ref_id WHERE l.project=? AND l.ref_kind='item' "
                        f"AND t.project=? AND t.kind='issue' AND t.status NOT IN {CLOSED} ORDER BY l.object_id", (proj, proj))] if m else []
                if not m: return self.send_error(404)
                issues = c4.issues_by_object(m, pathlib.Path(m.pop("root")))
                meta = {k: m.pop(k) for k in ("name", "layout", "tags") if k in m}
                return self.json({"meta": meta, **m, "issues": issues, "links": links, "open_issues": open_issues})
            if parts[1:2] == ["code"]:
                with lock: m = c4.read_model(conn, q.get("project") or default_project())
                if m:
                    segs = parts[2:]
                    hidden = any(x.startswith(".") for x in segs) or (segs and (segs[-1].endswith(".db") or ".sqlite" in segs[-1]))
                    try:
                        root = pathlib.Path(m["root"]); f = (root / "/".join(segs)).resolve()
                        if not hidden and f.is_relative_to(root) and f.is_file(): return self.file(f, "text/plain")
                    except (ValueError, OSError): pass
                return self.send_error(404)
            if parts[1:2] in (["vendor"], ["assets"]) and len(parts) == 3:
                try:
                    f = (VIEWER / parts[1] / parts[2]).resolve()
                    if f.parent == (VIEWER / parts[1]).resolve() and f.is_file(): return self.file(f)
                except (ValueError, OSError): pass
                return self.send_error(404)
            if p == "/api/pages":
                with lock: return self.json(db.list_pages(conn, q.get("project")))
            if parts[1:3] == ["api", "page"] and len(parts) in (5, 6):
                with lock: pg = db.get_page(conn, parts[3], parts[4])
                if not pg: return self.send_error(404)
                if len(parts) == 5: return self.json(pg)
                if parts[5] == "version":
                    with lock: dv = conn.execute("PRAGMA data_version").fetchone()[0]
                    return self.json({"version": f"{pg['updated_at']}:{dv}"})
            if p == "/api/query": return self.query(q)
            self.send_error(404)

        def query(self, q):
            src = q.pop("src", None); limit = q.pop("limit", "50")
            if src not in blocks.QUERY_COLS: return self.send_error(400, "src must be item|decision")
            if not (limit.isdigit() and 1 <= int(limit) <= 200): return self.send_error(400, "bad limit")
            where = q
            bad = [k for k in where if k not in blocks.QUERY_COLS[src] or where[k] == ""]
            if bad: return self.send_error(400, f"column not allowed or empty value: {bad[0]}")
            sql = f"SELECT {SHOW[src]} FROM {src}" + (" WHERE " + " AND ".join(f"{k}=?" for k in where) if where else "") + " ORDER BY id LIMIT ?"
            self.json(rows(sql, (*where.values(), int(limit))))

        def projects(self):
            out = rows("SELECT id,name,description,parent,status FROM project ORDER BY id")
            for r in out:
                pid = r["id"]
                r["tasks"] = {x["status"]: x["n"] for x in rows("SELECT status,count(*) n FROM item WHERE project=? AND kind='task' GROUP BY status", (pid,))}
                one = lambda sql: rows(sql, (pid,))[0]["n"]
                r["issues_open"] = one(f"SELECT count(*) n FROM item WHERE project=? AND kind='issue' AND status NOT IN {CLOSED}")
                r["issues_total"] = one("SELECT count(*) n FROM item WHERE project=? AND kind='issue'")
                r["decisions"] = one("SELECT count(*) n FROM decision WHERE project=?")
                r["pages"] = one("SELECT count(*) n FROM page WHERE project=?")
                r["docs"] = one("SELECT count(*) n FROM doc WHERE project=? AND status!='missing'")
                r["last_update"] = rows("SELECT max(t) m FROM (SELECT max(updated_at) t FROM item WHERE project=? UNION ALL SELECT max(updated_at) FROM page WHERE project=? "
                                        "UNION ALL SELECT max(updated_at) FROM doc WHERE project=? UNION ALL SELECT max(ts) FROM audit WHERE project=?)", (pid,) * 4)[0]["m"]
            return out

        def items(self, q):
            sql, args = ["SELECT id,project,kind,title,body,status,priority,owner,created_at,updated_at FROM item WHERE 1=1"], []
            for k, ok in (("kind", ITEM_KINDS), ("status", ITEM_STATUS)):
                if k in q:
                    if q[k] not in ok: return self.send_error(400, f"bad {k}")
                    sql.append(f"AND {k}=?"); args.append(q[k])
            if "id" in q:
                if not q["id"].isdigit(): return self.send_error(400, "bad id")
                sql.append("AND id=?"); args.append(int(q["id"]))
            if q.get("project"): sql.append("AND project=?"); args.append(q["project"])
            self.json(rows(" ".join(sql) + " ORDER BY id", args))

        def audit(self, q):
            limit = q.get("limit", "100")
            if not (limit.isdigit() and 1 <= int(limit) <= 500): return self.send_error(400, "bad limit")
            self.json(rows("SELECT * FROM audit" + (" WHERE project=?" if q.get("project") else "") + " ORDER BY id DESC LIMIT ?",
                           (*((q["project"],) if q.get("project") else ()), int(limit))))

        def search(self, q):
            terms = re.findall(r"\w+", db.fold(q.get("q", "")))
            if not terms: return self.send_error(400, "empty q")
            match = " ".join(f'"{t}"' for t in terms) + "*"  # quoted terms: no FTS syntax from user input; prefix on the last
            proj = q.get("project")
            hits = rows("SELECT src,ref,project,snippet(search,1,'','','…',12) snippet FROM search WHERE search MATCH ?" + (" AND project=?" if proj else "")
                        + " ORDER BY bm25(search) LIMIT 30", (match, proj) if proj else (match,))
            for h in hits:  # real title/key from the source row (the index holds the folded copy)
                col = {"item": "kind", "decision": "''", "page": "slug", "doc": "path"}[h["src"]]
                key = "id" if h["src"] in ("item", "decision") else "rowid"
                r = rows(f"SELECT title, {col} AS k FROM {SRC_TABLE[h['src']]} WHERE {key}=?", (h["ref"],))
                h["title"], h["key"] = (r[0]["title"], r[0]["k"]) if r else ("", "")
            self.json(hits)

        def file(self, f, ctype=None):
            body = f.read_bytes()
            self.send_response(200)
            ctype = ctype or TYPES.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a): pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
