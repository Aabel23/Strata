"""HTTP server: C4 viewer, pages and their JSON APIs. All data comes from the DB."""
import hmac, http.server, json, mimetypes, pathlib, re, secrets, socket, threading
from urllib.parse import parse_qs, unquote, urlsplit
from strata import blocks, c4_edit, c4_layered, codemap, db, service, symbols
from strata.chat import ChatError, ChatSupervisor

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
STATIC = {"/": "app.html", "/app.js": "app.js", "/app.css": "app.css", "/c4": "index.html", "/index.html": "index.html", "/page.js": "page.js", "/swimlane.js": "swimlane.js", "/page.css": "page.css"}
TYPES = {".html": "text/html", ".md": "text/plain", ".yaml": "text/plain", ".js": "application/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json"}
SHOW = {"item": "id,project,kind,label,title,status,priority,owner"}
ITEM_KINDS = ("rule", "task", "issue", "knowledge", "draft", "note", "step", "gate")
ITEM_STATUS = ("proposed", "approved", "open", "doing", "review", "done", "rejected")
CLOSED = "('done','rejected')"
def _open_issues(conn, project):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT l.object_id FROM c4_link l JOIN item t ON t.id=l.ref_id WHERE l.project=? AND l.ref_kind='item' "
        f"AND t.project=? AND t.label='issue' AND t.status NOT IN {CLOSED} ORDER BY l.object_id", (project, project))]
db.get_open_issues_objects = _open_issues
LOOPBACK = ("127.0.0.1", "::1", "localhost")
EDIT_PATH = "/api/c4/edit"
PROJECT_PATH = "/api/project"
ITEM_PATH = "/api/item"
CHAT_PATH = "/api/chat"
CHAT_EVENTS_PATH = "/api/chat/events"
CHAT_AUTH_PATH = "/api/chat/auth"
CHAT_DIFF_PATH = "/api/chat/diff"
MAX_BODY = 65536
CHAT_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
CHAT_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CODEMAP_BUILD_SLOT = threading.Semaphore(1)
_CODEMAP_BUILD_LOCK = threading.Lock()
_CODEMAP_BUILDS = set()
_CODEMAP_FAILURES = {}


def make_server(db_path=None, project=None, port=0, host="127.0.0.1", allow_hosts=(), bound_hosts=None, allow_edit=None, build=codemap.run_gitnexus, chat_supervisor_factory=ChatSupervisor):
    """allow_hosts: extra Host names (with or without port). bound_hosts: every address strata binds (default just host).
    allow_edit: enable POST /api/c4/edit; None = only when host is loopback. build: cancellable code-map builder (root, reindex=, cancel=) -> graph bytes."""
    if allow_edit is None: allow_edit = host in LOOPBACK
    if host in ("0.0.0.0", "::") and not allow_hosts:
        raise ValueError(f"binding {host} needs at least one --allow-host NAME")
    bound = [h.lower() for h in (bound_hosts or [host])]
    extra = {h.lower() for h in allow_hosts}
    db.init(db_path).close()
    conn = db.connect(db_path, check_same_thread=False)  # one long-lived conn: data_version needs it
    lock = threading.RLock()
    token = secrets.token_urlsafe(32)  # per start: a restart invalidates old pages; served by GET /api/session
    symc = []  # symbol cache conn, opened lazily on first /api/code/ call (derived data)

    def chat_projects():
        with lock:
            registered = {}
            for row in conn.execute(
                    "SELECT p.id,coalesce(nullif(p.root,''),m.root) root FROM project p "
                    "LEFT JOIN c4_meta m ON m.project=p.id WHERE coalesce(nullif(p.root,''),m.root) IS NOT NULL"):
                root = row["root"]
                try:
                    path = pathlib.Path(root).expanduser()
                    if not path.is_absolute():
                        path = pathlib.Path.cwd() / path
                    # Keep bad project registrations out of the chat registry;
                    # resolving a symlink here would incorrectly bless it.
                    current = pathlib.Path(path.anchor)
                    has_symlink = False
                    for part in path.parts[1:]:
                        if part in ("", "."):
                            continue
                        if part == "..":
                            current = current.parent
                            continue
                        current = current / part
                        if current.is_symlink():
                            has_symlink = True
                            break
                    if not has_symlink and path.is_dir():
                        registered[row["id"]] = str(path)
                except (OSError, TypeError, ValueError):
                    continue
            return registered

    chat_supervisor = chat_supervisor_factory(chat_projects())
    chat_stop_lock = threading.Lock()
    chat_stopped = False

    def refresh_chat_projects():
        chat_supervisor.refresh_projects(chat_projects())

    def stop_chat():
        nonlocal chat_stopped
        with chat_stop_lock:
            if chat_stopped:
                return
            chat_stopped = True
        chat_supervisor.shutdown()

    def rows(sql, args=()):
        with lock: return db.query_rows(conn, sql, args)

    bl = threading.Lock(); build_threads = set()
    stopping = threading.Event(); lifecycle = threading.Lock()

    def code_key(pid):
        path = db.db_path(db_path)
        return (str(pathlib.Path(path).resolve()) if path != ":memory:" else f":memory:{id(conn)}", pid)

    def build_codemap(pid, key):
        acquired = False
        try:
            while not stopping.is_set():
                acquired = _CODEMAP_BUILD_SLOT.acquire(timeout=0.1)
                if acquired: break
            if not acquired or stopping.is_set(): return
            with lock: root = codemap.project_root(conn, pid)
            body = build(root, reindex=True, cancel=stopping)  # slow: no DB lock held
            g = json.loads(body)
            if not isinstance(g, dict) or not isinstance(g.get("nodes"), list) or not isinstance(g.get("relationships"), list): raise RuntimeError("unexpected gitnexus graph shape")
            with lifecycle:
                if stopping.is_set(): return
                codemap.write_snapshot(codemap.snapshot_path(db.db_path(db_path), pid), body)
            with _CODEMAP_BUILD_LOCK: _CODEMAP_FAILURES.pop(key, None)
        except Exception as e:
            if not stopping.is_set():
                with _CODEMAP_BUILD_LOCK: _CODEMAP_FAILURES[key] = str(e) or type(e).__name__
        finally:
            if acquired: _CODEMAP_BUILD_SLOT.release()
            with _CODEMAP_BUILD_LOCK: _CODEMAP_BUILDS.discard(key)
            with bl:
                build_threads.discard(threading.current_thread())

    def stop_builds():
        with lifecycle: stopping.set()

    def wait_builds():
        with bl: workers = list(build_threads)
        for worker in workers: worker.join()

    stamps = {}  # project -> docs_dir fingerprint at last scan

    def autoscan():
        """Re-scan any project whose docs_dir changed, so new or edited docs show up without `doc scan`."""
        with lock:
            for r in db.list_projects_with_docs(conn):
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

        def _no(self, *a, **k): self.json({"error": "method not allowed"}, 405, Allow="POST" if urlsplit(self.path).path in (EDIT_PATH, PROJECT_PATH, ITEM_PATH, CHAT_PATH) else "GET")
        do_PUT = do_DELETE = do_PATCH = _no

        def do_POST(self):
            if not self.host_ok(): return self.json({"error": "forbidden host"}, 403)
            if not allow_edit: return self.json({"error": "editing disabled"}, 403)
            u = urlsplit(self.path)
            if u.path not in (EDIT_PATH, PROJECT_PATH, ITEM_PATH, CHAT_PATH): return self._no()
            h = self.headers
            if not hmac.compare_digest((h.get("X-Strata-Token") or "").encode(), token.encode()): return self.json({"error": "bad or missing X-Strata-Token"}, 403)
            if h.get("X-Strata-Edit") != "1": return self.json({"error": "X-Strata-Edit header required"}, 403)
            if h.get("Origin") is not None and h["Origin"].lower() != "http://" + (h.get("Host") or "").lower():
                return self.json({"error": "bad Origin"}, 403)
            if not (h.get("Content-Type") or "").lower().startswith("application/json"): return self.json({"error": "Content-Type must be application/json"}, 415)
            n = h.get("Content-Length")
            if n is None or not n.isdigit(): return self.json({"error": "Content-Length required"}, 413)
            if int(n) > MAX_BODY: return self.json({"error": "body too large"}, 413)
            try: op = json.loads(self.rfile.read(int(n)))
            except ValueError: op = None
            if not isinstance(op, dict): return self.json({"error": "JSON object body required"}, 400)
            if u.path == CHAT_PATH:
                if u.query: return self.json({"error": "query parameters are not allowed"}, 400)
                return self.chat_post(op)
            if u.path == PROJECT_PATH: return self.project_op(op)
            if u.path == ITEM_PATH: return self.item_op(op, parse_qs(u.query).get("project", [""])[-1])
            if not isinstance(op.get("yes", False), bool): return self.json({"error": "yes must be boolean"}, 400)
            yes = op.pop("yes", False)
            proj = parse_qs(u.query).get("project", [""])[-1] or default_project()
            if not proj: return self.json({"error": "project required"}, 400)
            try:
                with lock:
                    try:
                        r = c4_edit.apply(conn, proj, op, yes=yes)
                        model = {**c4_layered.read_model(conn, proj), **c4_layered.viewer_extra(conn, proj)}
                    except BaseException: conn.rollback(); raise
                return self.json({"ok": True, "changed": r.get("changed", []), "warnings": r.get("warnings", []), "model": model})
            except ValueError as e: return self.json({"error": str(e)}, 400)
            except KeyError as e: return self.json({"error": str(e.args[0]) if e.args else "not found"}, 404)
            except Exception: return self.json({"error": "internal error"}, 500)

        def project_op(self, op):
            """POST /api/project {op: add|edit|delete, ...}: project create/edit/delete through the service (audited)."""
            steps = pid = scan_root = None
            try:
                with lock:
                    try:
                        if op.get("op") == "add" and "setup" in op:
                            if not isinstance(op["setup"], bool): raise ValueError("setup must be boolean")
                            for k in ("id", "name", "root", "docs_dir"):
                                if op.get(k) is not None and not isinstance(op[k], str): raise ValueError(f"{k} must be a string")
                            if op["setup"] and not op.get("root"): raise ValueError("root required")
                        if op.get("op") == "add" and op.get("setup"):
                            steps = service.setup_project(conn, db.db_path(db_path), op["root"], op.get("id"), op.get("name"), op.get("docs_dir"), codemap=False, confine_docs=True)
                            pid = steps[0]["id"]
                            scan_root = pathlib.Path(op["root"]).expanduser().resolve()
                        elif op.get("op") == "add":
                            service.add_project(conn, op.get("id"), op.get("name"), op.get("root"), op.get("docs_dir"), op.get("parent"), op.get("description"))
                        elif op.get("op") == "edit":
                            if not isinstance(op.get("id"), str): raise ValueError("id required")
                            service.edit_project(conn, op["id"], *(op.get(k) for k in ("name", "root", "docs_dir", "parent", "description")))
                        elif op.get("op") == "delete":
                            if not isinstance(op.get("id"), str): raise ValueError("id required")
                            service.delete_project(conn, op["id"], op.get("confirm"))
                        else: raise ValueError("op must be add, edit or delete")
                    except BaseException: conn.rollback(); raise
                if scan_root is not None and service.has_code(scan_root):
                    key = code_key(pid)
                    with bl:
                        if not stopping.is_set():
                            steps[-1] = {"step": "codemap", "status": "started", "detail": "building in the background"}
                            with _CODEMAP_BUILD_LOCK:
                                _CODEMAP_FAILURES.pop(key, None)
                                fresh = key not in _CODEMAP_BUILDS
                                if fresh: _CODEMAP_BUILDS.add(key)
                            if fresh:
                                worker = threading.Thread(target=build_codemap, args=(pid, key), daemon=True)
                                build_threads.add(worker); worker.start()
                return self.json({"ok": True, "id": pid, "steps": steps} if steps else {"ok": True})
            except ValueError as e: return self.json({"error": str(e)}, 400)
            except KeyError as e: return self.json({"error": str(e.args[0]) if e.args else "not found"}, 404)
            except Exception: return self.json({"error": "internal error"}, 500)

        def chat_post(self, op):
            """Guarded POST /api/chat. All roots come from the refreshed DB registry."""
            try:
                refresh_chat_projects()
                operation = op.get("op")
                if operation == "login" and set(op) == {"op"}:
                    return self.json({"ok": True, **chat_supervisor.login_global()})
                project_id = op.get("project")
                if not isinstance(project_id, str) or not CHAT_PROJECT_ID.fullmatch(project_id):
                    raise ValueError("invalid project")
                if operation == "start":
                    if set(op) - {"op", "project", "provider", "model"}:
                        raise ValueError("unexpected start field")
                    provider = op.get("provider", "codex")
                    model = op.get("model")
                    if provider not in ("codex", "openrouter", "omniroute"):
                        raise ValueError("invalid provider")
                    if model is not None and (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model)):
                        raise ValueError("invalid model")
                    roots = chat_projects()
                    root = roots.get(project_id)
                    if not root:
                        return self.json({"error": "project is not registered for chat"}, 404)
                    result = chat_supervisor.start(project_id, root, provider=provider, model=model)
                    return self.json({"ok": True, **result})

                required = {"op", "project", "session_id"}
                if operation in ("turn", "decide", "cancel", "close", "login", "cancel_login"):
                    if not required.issubset(op):
                        raise ValueError("missing chat fields")
                session_id = op.get("session_id")
                if not isinstance(session_id, str) or not CHAT_SESSION_ID.fullmatch(session_id):
                    raise ValueError("invalid session ID")
                if operation == "turn":
                    if set(op) != required | {"message"} or not isinstance(op.get("message"), str) or not op["message"].strip() or len(op["message"]) > 100_000:
                        raise ValueError("invalid turn message")
                    return self.json({"ok": True, "turn_id": chat_supervisor.turn(project_id, session_id, op["message"])})
                if operation == "decide":
                    if set(op) != required | {"approval_id", "allow"} or not isinstance(op.get("approval_id"), str) or not op["approval_id"] or len(op["approval_id"]) > 128 or not isinstance(op.get("allow"), bool):
                        raise ValueError("invalid approval decision")
                    return self.json({"ok": True, "accepted": chat_supervisor.decide(project_id, session_id, op["approval_id"], op["allow"])})
                if operation == "cancel":
                    if set(op) != required: raise ValueError("unexpected cancel field")
                    return self.json({"ok": True, "cancelled": chat_supervisor.cancel(project_id, session_id)})
                if operation == "close":
                    if set(op) != required: raise ValueError("unexpected close field")
                    return self.json({"ok": True, "closed": chat_supervisor.close(project_id, session_id)})
                if operation == "login":
                    if set(op) != required: raise ValueError("unexpected login field")
                    return self.json({"ok": True, **chat_supervisor.login(project_id, session_id)})
                if operation == "cancel_login":
                    if set(op) != required | {"login_id"} or not isinstance(op.get("login_id"), str) or not op["login_id"] or len(op["login_id"]) > 256:
                        raise ValueError("invalid login ID")
                    return self.json({"ok": True, "cancelled": chat_supervisor.cancel_login(project_id, session_id, op["login_id"])})
                raise ValueError("invalid chat operation")
            except ValueError:
                return self.json({"error": "invalid chat request"}, 400)
            except ChatError:
                return self.json({"error": "chat request could not be completed"}, 409)
            except Exception:
                return self.json({"error": "chat service unavailable"}, 503)

        def chat_get(self, path, raw_query):
            if not hmac.compare_digest((self.headers.get("X-Strata-Token") or "").encode(), token.encode()):
                return self.json({"error": "bad or missing X-Strata-Token"}, 403)
            try:
                parsed = parse_qs(raw_query, keep_blank_values=True, strict_parsing=True)
                allowed = {CHAT_EVENTS_PATH: {"project", "session_id", "after"},
                           CHAT_AUTH_PATH: {"provider"}, CHAT_DIFF_PATH: {"project", "session_id"}}[path]
                if any(k not in allowed or len(v) != 1 for k, v in parsed.items()):
                    raise ValueError
                q = {k: values[0] for k, values in parsed.items()}
                refresh_chat_projects()
                if path == CHAT_AUTH_PATH:
                    provider = q.get("provider", "codex")
                    if provider not in ("codex", "openrouter", "omniroute"):
                        raise ValueError
                    return self.json(chat_supervisor.auth_status(provider))
                project_id, session_id = q.get("project"), q.get("session_id")
                if not project_id or not CHAT_PROJECT_ID.fullmatch(project_id) or not session_id or not CHAT_SESSION_ID.fullmatch(session_id):
                    raise ValueError
                if path == CHAT_EVENTS_PATH:
                    after_text = q.get("after", "0")
                    if not re.fullmatch(r"[0-9]{1,19}", after_text) or int(after_text) > 2**63 - 1:
                        raise ValueError
                    return self.json({"events": chat_supervisor.events(project_id, session_id, int(after_text))})
                return self.json(chat_supervisor.diff_status(project_id, session_id))
            except ValueError:
                return self.json({"error": "invalid chat query"}, 400)
            except ChatError:
                return self.json({"error": "chat request could not be completed"}, 409)
            except Exception:
                return self.json({"error": "chat service unavailable"}, 503)

        def item_op(self, op, proj):
            """POST /api/item {op: add|edit|delete|dep_add|dep_rm, ...}: task/issue writes as role main through the service (audited)."""
            def need(k, t):
                if not isinstance(op.get(k), t) or isinstance(op.get(k), bool): raise ValueError(f"{k} required")
                return op[k]
            def opt(k, t):
                if op.get(k) is not None and not isinstance(op[k], t): raise ValueError(f"{k} must be {t.__name__}")
                return op.get(k)
            try:
                with lock:
                    try:
                        o, out = op.get("op"), {}
                        if o == "add":
                            kind = need("kind", str)
                            if kind != "issue" and kind not in ITEM_KINDS: raise ValueError("bad kind")
                            if opt("status", str) is not None and op["status"] not in ITEM_STATUS: raise ValueError("bad status")
                            if not need("title", str).strip(): raise ValueError("title required")
                            out["id"] = service.add_item(conn, "main", proj or need("project", str), kind, need("title", str),
                                                         opt("body", str), opt("priority", str), op.get("status"), opt("spec", dict), opt("label", str))
                        elif o == "edit":
                            id = need("id", int)
                            if opt("status", str) is not None and op["status"] not in ITEM_STATUS: raise ValueError("bad status")
                            if opt("title", str) is not None and not op["title"].strip(): raise ValueError("title required")
                            f = {k: opt(k, t) for k, t in (("title", str), ("body", str), ("priority", str), ("spec", dict))}
                            if op.get("status") is None and all(v is None for v in f.values()): raise ValueError("nothing to edit")
                            if f["spec"] is not None and "scope" in f["spec"] and not isinstance(f["spec"]["scope"], dict): raise ValueError("spec.scope must be a JSON object")
                            if op.get("status") is not None: service.set_item(conn, "main", id, status=op["status"])  # first: transition rules are the likeliest failure
                            if any(v is not None for v in f.values()): service.edit_item(conn, "main", id, **f)
                        elif o == "delete": service.delete_item(conn, "main", need("id", int))
                        elif o in ("dep_add", "dep_rm"): service.dep(conn, "main", need("id", int), need("depends_on", int), o == "dep_add")
                        else: raise ValueError("op must be add, edit, delete, dep_add or dep_rm")
                    except BaseException: conn.rollback(); raise
                return self.json({"ok": True, **out})
            except ValueError as e: return self.json({"error": str(e)}, 400)
            except KeyError as e: return self.json({"error": str(e.args[0]) if e.args else "not found"}, 404)
            except PermissionError as e: return self.json({"error": str(e)}, 403)
            except Exception: return self.json({"error": "internal error"}, 500)

        def do_GET(self):
            if not self.host_ok(): return self.send_error(403)
            u = urlsplit(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            parts = [unquote(x) for x in u.path.split("/")]  # ['', 'api', ...]
            p = u.path
            if p in (CHAT_EVENTS_PATH, CHAT_AUTH_PATH, CHAT_DIFF_PATH):
                return self.chat_get(p, u.query)
            if p in STATIC: return self.file(VIEWER / STATIC[p])
            if p in ("/api/projects", "/api/docs", "/api/doc", "/api/search"): autoscan()
            if p == "/api/session": return self.json({"token": token}, **{"Cache-Control": "no-store"})
            if p == "/api/version":  # viewer polls this; any CLI/MCP commit or docs edit changes it
                autoscan()
                with lock: dv = db.get_data_version(conn); ds = hash(repr(sorted(stamps.items(), key=str)))
                return self.json({"version": f"{dv}:{ds}"})
            if p == "/api/doc": return self.doc(q)
            if p == "/api/projects": return self.json(self.projects())
            if p == "/api/project-usage":
                with lock: return self.json(db.project_usage(conn, q.get("project", "")))
            if p == "/api/items": return self.items(q)
            if p == "/api/docs":
                return self.json(rows("SELECT project,path,title,feature,kind,status,ord,updated_at,summary,json(code) code FROM doc" + (" WHERE project=?" if q.get("project") else "")
                                      + " ORDER BY project,ord,path", (q["project"],) if q.get("project") else ()))
            if p == "/api/codemap": return self.codemap(q)
            if p.startswith("/api/code/"): return self.code(p, q)
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
                    open_issues = db.get_open_issues_objects(conn, proj) if m else []
                if not m: return self.send_error(404)
                m.pop("root")
                meta = {"name": m.pop("name")}
                return self.json({"meta": meta, **m, "links": links, "open_issues": open_issues, **extra})
            if parts[1:2] == ["code"]:
                with lock: m = c4_layered.read_model(conn, q.get("project") or default_project())
                f = m and servable(m["root"], parts[2:])
                return self.file(f, "text/plain") if f else self.send_error(404)
            if parts[1:2] == ["codemap"]:
                f = servable(VIEWER / "codemap", parts[2:] if parts[2:] != [""] else ["index.html"])
                return self.file(f) if f else self.send_error(404)
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
                    with lock: dv = db.get_data_version(conn)
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
            out = rows("SELECT id,name,description,parent,status,root,docs_dir FROM project ORDER BY id")
            for r in out:
                pid = r["id"]
                r["tasks"] = {x["status"]: x["n"] for x in rows("SELECT status,count(*) n FROM item WHERE project=? AND kind='task' AND coalesce(label,'')!='issue' GROUP BY status", (pid,))}
                one = lambda sql: rows(sql, (pid,))[0]["n"]
                r["issues_open"] = one(f"SELECT count(*) n FROM item WHERE project=? AND label='issue' AND status NOT IN {CLOSED}")
                r["issues_total"] = one("SELECT count(*) n FROM item WHERE project=? AND label='issue'")
                r["pages"] = one("SELECT count(*) n FROM page WHERE project=?")
                r["docs"] = one("SELECT count(*) n FROM doc WHERE project=? AND status!='missing'")
                r["last_update"] = rows("SELECT max(t) m FROM (SELECT max(updated_at) t FROM item WHERE project=? UNION ALL SELECT max(updated_at) FROM page WHERE project=? "
                                        "UNION ALL SELECT max(updated_at) FROM doc WHERE project=? UNION ALL SELECT max(ts) FROM audit WHERE project=?)", (pid,) * 4)[0]["m"]
            return out

        def items(self, q):
            """List (filters kind/label/status/owner/project/ready; kind=issue = task+label issue, id order; ready: priority order) or, with id, the item plus deps, links and history."""
            for k, ok in (("kind", ITEM_KINDS), ("status", ITEM_STATUS)):
                if k in q and q[k] not in ok: return self.send_error(400, f"bad {k}")
            if "id" in q and not q["id"].isdigit(): return self.send_error(400, "bad id")
            ready = q.get("ready") == "1"
            with lock:
                out = service.list_items(conn, q.get("project") or None, q.get("kind"), q.get("status"), q.get("owner") or None, ready, q.get("label") or None)
                if "id" in q: out = [r for r in out if r["id"] == int(q["id"])]
                if not ready: out.sort(key=lambda r: r["id"])
                if "id" in q and out: out[0].update(self.detail(out[0]))
            self.json(out)

        def detail(self, it):
            """deps both ways, C4 objects linked to them, audit history for one item."""
            d = service.get_item(conn, it["id"])
            objs = db.get_item_c4_objects(conn, it["project"], it["id"])
            hist = []
            for r in db.get_item_audit(conn, it["id"]):
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

        def codemap(self, q):
            if not q.get("project"): return self.json({"error": "missing project"}, 400)
            with lock:
                if not conn.execute("SELECT 1 FROM project WHERE id=?", (q["project"],)).fetchone(): return self.json({"error": "unknown project"}, 400)
            try:
                graph = codemap.load_snapshot(db.db_path(db_path), q["project"])
                if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("relationships"), list):
                    return self.json({"error": "corrupt code map snapshot", "building": False}, 503)
                return self.json(graph)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self.json({"error": "corrupt code map snapshot", "building": False}, 503)
            except FileNotFoundError: pass
            key = code_key(q["project"])
            with _CODEMAP_BUILD_LOCK: busy, why = key in _CODEMAP_BUILDS, _CODEMAP_FAILURES.get(key)
            if busy: return self.json({"error": "building", "building": True}, 404)
            if why: return self.json({"error": why, "building": False}, 404)
            with lock: row = conn.execute("SELECT root FROM project WHERE id=?", (q["project"],)).fetchone()
            return self.json({"error": "no code map", "empty": True, "root": (row and row[0]) or None}, 404)

        def code(self, p, q):
            need = {"/api/code/files": ("project", "object"), "/api/code/symbols": ("project", "path"), "/api/code/src": ("project", "id")}.get(p)
            if not need: return self.json({"error": "not found"}, 404)
            if not all(q.get(k) for k in need): return self.json({"error": "missing " + " and ".join(need)}, 400)
            try:
                with lock:
                    if p == "/api/code/files": return self.json(c4_layered.component_files(conn, q["project"], q["object"]))
                    root = db.get_project_root_or_c4_root(conn, q["project"])
                    if not root: raise KeyError("project has no root")
                    if not symc:
                        c = db.connect(symbols.cache_path(db.db_path(db_path)), check_same_thread=False)
                        c.executescript(symbols.SCHEMA); symc.append(c)  # like symbols.connect, but shared across handler threads under `lock`
                    sc = symc[0]
                    if p == "/api/code/symbols": return self.json(symbols.file_outline(sc, q["project"], root, q["path"]))
                    return self.json(symbols.source_of(sc, q["project"], root, q["id"]))
            except ValueError as e: return self.json({"error": str(e)}, 400)
            except KeyError as e: return self.json({"error": str(e.args[0]) if e.args else "not found"}, 404)
            except FileNotFoundError as e: return self.json({"error": f"not found: {e.args[0] if e.args else ''}"}, 404)

        def json(self, obj, code=200, **hdr):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            for k, v in hdr.items(): self.send_header(k, v)
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
        def serve_forever(self, *args, **kwargs):
            try: return super().serve_forever(*args, **kwargs)
            finally: stop_builds(); stop_chat(); wait_builds()
        def shutdown(self):
            stop_builds(); stop_chat()
            return super().shutdown()
        def server_close(self):
            stop_builds(); stop_chat()
            super().server_close()
            wait_builds()
    return S((host, port), H)
