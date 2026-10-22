"""HTTP server: C4 viewer, pages and their JSON APIs. All data comes from the DB."""
import http.server, json, mimetypes, pathlib, re, socket, sqlite3, threading
from urllib.parse import parse_qs, unquote, urlsplit
from strata import blocks, c4_layered, db, roadmap, service

SERVE_EXT = set(".py .js .mjs .ts .tsx .css .html .htm .md .txt .yaml .yml .json .toml .c .h .cpp .hpp .dart .java .kt .go .rs .svg .png .jpg .jpeg .gif .webp".split())

def servable(root, segs):
    """File under root that /code/ and /docs/ may serve, else None. Extension allowlist; no dot/empty/'..'/NUL segments."""
    if not segs or any(x in ("", "..") or x.startswith(".") or "\0" in x for x in segs): return None
    try:
        root = pathlib.Path(root).resolve(); f = (root / "/".join(segs)).resolve()
    except (ValueError, OSError): return None
    if not f.is_relative_to(root) or any(x.startswith(".") for x in f.relative_to(root).parts): return None  # symlink into a dot-dir
    return f if f.suffix.lower() in SERVE_EXT and f.is_file() else None

VIEWER = pathlib.Path(__file__).resolve().parent.parent / "viewer"
STATIC = {"/": "app.html", "/app.js": "app.js", "/app.css": "app.css", "/c4": "index.html", "/index.html": "index.html", "/page.js": "page.js", "/swimlane.js": "swimlane.js", "/roadmap.js": "roadmap.js", "/page.css": "page.css"}
TYPES = {".html": "text/html", ".md": "text/plain", ".yaml": "text/plain", ".js": "application/javascript", ".css": "text/css", ".json": "application/json"}
SHOW = {"item": "id,project,kind,title,status,priority,owner"}
ITEM_KINDS = ("rule", "task", "issue", "knowledge", "draft", "note", "step", "gate")
ITEM_STATUS = ("proposed", "approved", "open", "doing", "review", "done", "rejected")
CLOSED = "('done','rejected')"


def make_server(db_path=None, project=None, port=0, host="127.0.0.1", allow_hosts=(), bound_hosts=None):
    """allow_hosts: extra Host names (with or without port). bound_hosts: every address strata binds (default just host)."""
    if host in ("0.0.0.0", "::") and not allow_hosts:
        raise ValueError(f"binding {host} needs at least one --allow-host NAME")
    bound = [h.lower() for h in (bound_hosts or [host])]
    extra = {h.lower() for h in allow_hosts}
    db.init(db_path).close()
    conn = sqlite3.connect(db.db_path(db_path), check_same_thread=False)  # one long-lived conn: data_version needs it
    conn.row_factory = sqlite3.Row
    lock = threading.RLock()

    def rows(sql, args=()):
        with lock: return [dict(r) for r in conn.execute(sql, args)]

    stamps = {}  # project -> docs_dir fingerprint at last scan

    def autoscan():
        """Re-scan any project whose docs_dir changed, so new or edited docs show up without `doc scan`."""
        with lock:
            for r in conn.execute("SELECT id,docs_dir FROM project WHERE docs_dir IS NOT NULL").fetchall():
                base = pathlib.Path(r["docs_dir"])
                if not base.is_dir(): continue
                st = db.docs_stamp(base)
                if stamps.get(r["id"]) != st:
                    db.scan_docs(conn, r["id"], audit_row=False); stamps[r["id"]] = st

    def default_project():
        ps = rows("SELECT project FROM c4_meta")
        return project or (ps[0]["project"] if len(ps) == 1 else None)

    class H(http.server.BaseHTTPRequestHandler):
        def host_ok(self):
            port = self.server.server_address[1]
            ok = {f"[{h}]:{port}" if ":" in h else f"{h}:{port}" for h in bound} | {f"localhost:{port}", f"127.0.0.1:{port}"} | extra | {f"{h}:{port}" for h in extra}
            return (self.headers.get("Host") or "").lower() in ok  # DNS rebinding guard

        def do_GET(self):
            if not self.host_ok(): return self.send_error(403)
            u = urlsplit(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            parts = [unquote(x) for x in u.path.split("/")]  # ['', 'api', ...]
            p = u.path
            if p in STATIC: return self.file(VIEWER / STATIC[p])
            if p in ("/api/projects", "/api/docs", "/api/doc", "/api/search"): autoscan()
            if p == "/api/version":  # viewer polls this; any CLI/MCP commit or docs edit changes it
                autoscan()
                with lock: dv = conn.execute("PRAGMA data_version").fetchone()[0]; ds = hash(repr(sorted(stamps.items(), key=str)))
                return self.json({"version": f"{dv}:{ds}"})
            if p == "/api/doc": return self.doc(q)
            if p == "/api/projects": return self.json(self.projects())
            if p == "/api/items": return self.items(q)
            if p == "/api/docs":
                return self.json(rows("SELECT project,path,title,feature,kind,status,ord,updated_at,summary,json(code) code FROM doc" + (" WHERE project=?" if q.get("project") else "")
                                      + " ORDER BY project,ord,path", (q["project"],) if q.get("project") else ()))
            if p == "/api/roadmap":
                if not q.get("project"): return self.send_error(400, "project required")
                with lock: out = roadmap.api(conn, q["project"], q.get("roadmap") or None, q.get("only") == "version")
                return self.json(out) if out is not None else self.send_error(404)
            if p == "/api/audit": return self.audit(q)
            if p == "/api/search": return self.search(q)
            if parts[1:2] == ["docs"] and len(parts) > 3:
                with lock: r = rows("SELECT docs_dir FROM project WHERE id=?", (parts[2],))
                f = r and r[0]["docs_dir"] and servable(r[0]["docs_dir"], parts[3:])
                return self.file(f) if f else self.send_error(404)
            if p == "/pages": return self.file(VIEWER / "page.html")
            if parts[1:2] == ["page"] and len(parts) == 4:
                with lock: ok = db.get_page(conn, parts[2], parts[3])
                return self.file(VIEWER / "page.html") if ok else self.send_error(404)
            if p == "/api/c4":
                proj = q.get("project") or default_project()
                with lock:
                    m = c4_layered.read_model(conn, proj)
                    extra = c4_layered.viewer_extra(conn, proj) if m else {}
                    links = db.links_for(conn, proj) if m else {}
                    open_issues = [r["object_id"] for r in conn.execute(
                        "SELECT DISTINCT l.object_id FROM c4_link l JOIN item t ON t.id=l.ref_id WHERE l.project=? AND l.ref_kind='item' "
                        f"AND t.project=? AND t.kind='issue' AND t.status NOT IN {CLOSED} ORDER BY l.object_id", (proj, proj))] if m else []
                if not m: return self.send_error(404)
                m.pop("root")
                meta = {"name": m.pop("name")}
                return self.json({"meta": meta, **m, "links": links, "open_issues": open_issues, **extra})
            if parts[1:2] == ["code"]:
                with lock: m = c4_layered.read_model(conn, q.get("project") or default_project())
                f = m and servable(m["root"], parts[2:])
                return self.file(f, "text/plain") if f else self.send_error(404)
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
            if src not in SHOW: return self.send_error(400, "src must be item")
            if not (limit.isdigit() and 1 <= int(limit) <= 200): return self.send_error(400, "bad limit")
            where = q
            bad = [k for k in where if k not in blocks.QUERY_COLS[src] or where[k] == ""]
            if bad: return self.send_error(400, f"column not allowed or empty value: {bad[0]}")
            sql = f"SELECT {SHOW[src]} FROM {src}" + (" WHERE " + " AND ".join(f"{k}=?" for k in where) if where else "") + " ORDER BY id LIMIT ?"
            self.json(rows(sql, (*where.values(), int(limit))))

        def doc(self, q):
            """One YAML doc, parsed and validated, ready for the block renderer."""
            with lock: r = rows("SELECT docs_dir FROM project WHERE id=?", (q.get("project", ""),))
            path = q.get("path", "")
            if not r or not r[0]["docs_dir"] or not path.endswith(".yaml") or any(x.startswith(".") for x in path.split("/")): return self.send_error(404)
            try:
                root = pathlib.Path(r[0]["docs_dir"]).resolve(); f = (root / path).resolve()
                if not (f.is_relative_to(root) and f.is_file()): return self.send_error(404)
                d, errs = blocks.load_doc(f.read_text(encoding="utf-8", errors="replace"))
            except (ValueError, OSError): return self.send_error(404)
            self.json({**d, "errors": errs, "mtime": f.stat().st_mtime_ns})

        def projects(self):
            out = rows("SELECT id,name,description,parent,status FROM project ORDER BY id")
            for r in out:
                pid = r["id"]
                r["tasks"] = {x["status"]: x["n"] for x in rows("SELECT status,count(*) n FROM item WHERE project=? AND kind='task' GROUP BY status", (pid,))}
                one = lambda sql: rows(sql, (pid,))[0]["n"]
                r["issues_open"] = one(f"SELECT count(*) n FROM item WHERE project=? AND kind='issue' AND status NOT IN {CLOSED}")
                r["issues_total"] = one("SELECT count(*) n FROM item WHERE project=? AND kind='issue'")
                r["pages"] = one("SELECT count(*) n FROM page WHERE project=?")
                r["docs"] = one("SELECT count(*) n FROM doc WHERE project=? AND status!='missing'")
                r["last_update"] = rows("SELECT max(t) m FROM (SELECT max(updated_at) t FROM item WHERE project=? UNION ALL SELECT max(updated_at) FROM page WHERE project=? "
                                        "UNION ALL SELECT max(updated_at) FROM doc WHERE project=? UNION ALL SELECT max(ts) FROM audit WHERE project=?)", (pid,) * 4)[0]["m"]
            return out

        def items(self, q):
            """List (filters kind/status/owner/project/ready, id order; ready: priority order) or, with id, the item plus deps, links and history."""
            for k, ok in (("kind", ITEM_KINDS), ("status", ITEM_STATUS)):
                if k in q and q[k] not in ok: return self.send_error(400, f"bad {k}")
            if "id" in q and not q["id"].isdigit(): return self.send_error(400, "bad id")
            ready = q.get("ready") == "1"
            with lock:
                out = service.list_items(conn, q.get("project") or None, q.get("kind"), q.get("status"), q.get("owner") or None, ready)
                if "id" in q: out = [r for r in out if r["id"] == int(q["id"])]
                roadmap.annotate(conn, out)
                if not ready: out.sort(key=lambda r: r["id"])
                if "id" in q and out: out[0].update(self.detail(out[0]))
            self.json(out)

        def detail(self, it):
            """deps both ways, C4 objects linked to them, audit history for one item."""
            d = service.get_item(conn, it["id"])
            objs = [r["object_id"] for r in conn.execute("SELECT object_id FROM c4_link WHERE project=? AND ref_kind='item' AND ref_id=? ORDER BY object_id", (it["project"], it["id"]))]
            hist = []
            for r in conn.execute("SELECT ts,actor_role,tool,before,after FROM audit WHERE target=? ORDER BY id DESC", (f"item:{it['id']}",)):
                b, a = (json.loads(r[k]) if r[k] else None for k in ("before", "after"))
                b, a = b if isinstance(b, dict) else {}, a if isinstance(a, dict) else {}
                hist.append({"time": r["ts"], "actor": a.get("actor") or r["actor_role"], "tool": r["tool"], "from": b.get("status"), "to": a.get("status"), "note": a.get("note")})
            return {"deps": {"needs": d["depends_on"], "blocks": d["blocks"]}, "links": {"c4": objs}, "history": hist}

        def audit(self, q):
            limit = q.get("limit", "100")
            if not (limit.isdigit() and 1 <= int(limit) <= 500): return self.send_error(400, "bad limit")
            self.json(rows("SELECT * FROM audit" + (" WHERE project=?" if q.get("project") else "") + " ORDER BY id DESC LIMIT ?",
                           (*((q["project"],) if q.get("project") else ()), int(limit))))

        def search(self, q):
            try:
                with lock: hits = service.search(conn, q.get("q", ""), q.get("project"), q.get("src"), q.get("limit", 30))
            except ValueError as e: return self.send_error(400, str(e))
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

        def send_response_only(self, code, message=None):
            """The HTTP status line is Latin-1 only; our 400 messages (validation text) are Vietnamese
            and can contain characters outside it, which crashes the connection instead of sending the 400.
            Fall back to a lossy replace for the status line only — the real text still reaches the body."""
            try: http.server.BaseHTTPRequestHandler.send_response_only(self, code, message)
            except UnicodeEncodeError:
                http.server.BaseHTTPRequestHandler.send_response_only(self, code, (message or "").encode("latin-1", "replace").decode("latin-1"))

        def log_message(self, *a): pass

    class S(http.server.ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
    return S((host, port), H)
