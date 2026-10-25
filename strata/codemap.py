"""Code map snapshot: raw GitNexus graph ({nodes, relationships}) stored next to the DB; gitnexus is only ever a subprocess."""
import json, math, os, pathlib, queue, shutil, socket, subprocess, tempfile, threading, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"


def snapshot_path(db_path, project):
    """<db dir>/<db stem>.codemap/<project>.json (like symbols.cache_path)."""
    p = pathlib.Path(db_path); return p.with_name(p.stem + ".codemap") / f"{project}.json"


def project_root(conn, project):
    r = conn.execute("SELECT coalesce(p.root, m.root) FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (project,)).fetchone()
    if not r: raise KeyError(f"unknown project {project!r}")
    if not r[0]: raise ValueError(f"project {project!r} has no root")
    return r[0]


def gitnexus_cmd():
    """argv prefix: $STRATA_GITNEXUS (a .js file runs with node) > vendored tools/gitnexus via node > `gitnexus` on PATH."""
    env = os.environ.get("STRATA_GITNEXUS")
    if env: return ["node", env] if env.endswith((".js", ".mjs", ".cjs")) else [env]
    if (HERE / "tools/gitnexus/node_modules").is_dir(): return ["node", str(HERE / "tools/gitnexus/dist/cli/index.js")]
    if shutil.which("gitnexus"): return ["gitnexus"]
    raise RuntimeError("gitnexus not found: set STRATA_GITNEXUS, install tools/gitnexus, or put `gitnexus` on PATH")


def free_port():
    with socket.socket() as s: s.bind((HOST, 0)); return s.getsockname()[1]


def http_get(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r: return r.read()


def same_path(a, b): return os.path.realpath(a) == os.path.realpath(b)


def _failure(message, log):
    log.flush(); end = log.seek(0, os.SEEK_END); log.seek(max(0, end - 4096))
    tail = log.read(4096).decode("utf-8", errors="replace").strip()
    return f"{message}\nGitNexus output (last 4 KiB):\n{tail}" if tail else message


def _check_build(deadline, cancel, stage):
    if cancel is not None and cancel.is_set(): raise RuntimeError(f"gitnexus build cancelled during {stage}")
    if time.monotonic() >= deadline: raise RuntimeError(f"gitnexus build timed out during {stage}")


def _stop_child(child):
    try: child.terminate()
    except ProcessLookupError: pass
    try: child.wait(10)
    except Exception:
        child.kill(); child.wait(10)


def _wait_child(child, deadline, cancel, stage):
    while True:
        _check_build(deadline, cancel, stage)
        code = child.poll()
        if code is not None: return code
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def _fetch(url, fetch, deadline, cancel, stage):
    _check_build(deadline, cancel, stage)
    result = queue.Queue(maxsize=1)
    def request():
        try:
            if fetch is http_get:
                value = fetch(url, timeout=max(0.001, min(120, deadline - time.monotonic())))
            else:
                value = fetch(url)
            result.put((True, value))
        except Exception as exc: result.put((False, exc))
    threading.Thread(target=request, daemon=True).start()
    while True:
        _check_build(deadline, cancel, stage)
        try: ok, value = result.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
        except queue.Empty: continue
        _check_build(deadline, cancel, stage)
        if not ok: raise value
        return value


def run_gitnexus(root, reindex=False, spawn=subprocess.Popen, fetch=http_get, wait=30, cancel=None, timeout=300):
    """Raw bytes of GitNexus's /api/graph for the repo at `root`. Never runs plain `analyze` (it writes AGENTS.md/CLAUDE.md into the repo)."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")
    cmd = gitnexus_cmd()
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile() as log:
        if reindex:
            _check_build(deadline, cancel, "analyze")
            child = spawn([*cmd, "analyze", "--index-only", str(root)], stdout=log, stderr=subprocess.STDOUT)
            failure = None
            try:
                code = _wait_child(child, deadline, cancel, "analyze")
                if code: failure = RuntimeError(f"gitnexus analyze --index-only failed (exit {code})")
            except Exception as exc:
                failure = exc
            finally:
                _stop_child(child)
            if failure is not None: raise RuntimeError(_failure(str(failure), log)) from failure
        port = free_port(); base = f"http://{HOST}:{port}/api"
        _check_build(deadline, cancel, "serve startup")
        child = spawn([*cmd, "serve", "--port", str(port), "--host", HOST], stdout=log, stderr=subprocess.STDOUT)
        failure = None
        try:
            health_end = min(deadline, time.monotonic() + wait)
            while True:
                try: _fetch(base + "/health", fetch, deadline, cancel, "serve health check"); break
                except OSError:
                    if child.poll() is not None: raise RuntimeError("gitnexus serve exited during startup")
                    _check_build(deadline, cancel, "serve health check")
                    if time.monotonic() >= health_end:
                        if health_end == deadline: _check_build(deadline, cancel, "serve health check")
                        raise RuntimeError(f"gitnexus serve not healthy in {wait}s")
                    time.sleep(min(0.25, health_end - time.monotonic()))
            repos = json.loads(_fetch(base + "/repos", fetch, deadline, cancel, "repository lookup"))
            repos = repos.get("repos", []) if isinstance(repos, dict) else repos
            name = next((r["name"] for r in repos if same_path(r.get("path", ""), root)), None)
            if not name: raise RuntimeError(f"no gitnexus index for {root}; pass --reindex")
            graph = _fetch(base + "/graph?repo=" + urllib.request.quote(name), fetch, deadline, cancel, "graph fetch")
        except Exception as exc:
            failure = exc
        finally:
            _stop_child(child)
        if failure is None:
            try: _check_build(deadline, cancel, "serve cleanup")
            except Exception as exc: failure = exc
        if failure is not None: raise RuntimeError(_failure(str(failure), log)) from failure
        return graph


def write_snapshot(path, body):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp"); tmp.write_bytes(body); os.replace(tmp, path)


def snapshot(conn, db_path, project, reindex=False, **kw):
    """Build and write the snapshot; returns (path, graph) for reporting."""
    body = run_gitnexus(project_root(conn, project), reindex, **kw)
    g = json.loads(body)
    if not isinstance(g, dict) or "nodes" not in g or "relationships" not in g: raise RuntimeError("unexpected gitnexus graph shape")
    cancel = kw.get("cancel")
    if cancel is not None and cancel.is_set(): raise RuntimeError("gitnexus build cancelled before snapshot write")
    p = snapshot_path(db_path, project); write_snapshot(p, body); return p, g


def load_snapshot(db_path, project):
    """Parsed snapshot; FileNotFoundError when none."""
    return json.loads(snapshot_path(db_path, project).read_bytes())
