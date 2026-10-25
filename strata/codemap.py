"""Code map snapshot: raw GitNexus graph ({nodes, relationships}) stored next to the DB; gitnexus is only ever a subprocess."""
import json, os, pathlib, shutil, socket, subprocess, time, urllib.request

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


def http_get(url):
    with urllib.request.urlopen(url, timeout=120) as r: return r.read()


def same_path(a, b): return os.path.realpath(a) == os.path.realpath(b)


def run_gitnexus(root, reindex=False, spawn=subprocess.Popen, run=subprocess.run, fetch=http_get, wait=30):
    """Raw bytes of GitNexus's /api/graph for the repo at `root`. Never runs plain `analyze` (it writes AGENTS.md/CLAUDE.md into the repo)."""
    cmd = gitnexus_cmd()
    if reindex and run([*cmd, "analyze", "--index-only", str(root)]).returncode: raise RuntimeError("gitnexus analyze --index-only failed")
    port = free_port(); base = f"http://{HOST}:{port}/api"
    child = spawn([*cmd, "serve", "--port", str(port), "--host", HOST])
    try:
        end = time.monotonic() + wait
        while True:
            try: fetch(base + "/health"); break
            except OSError:
                if child.poll() is not None: raise RuntimeError("gitnexus serve exited during startup")
                if time.monotonic() > end: raise RuntimeError(f"gitnexus serve not healthy in {wait}s")
                time.sleep(0.25)
        repos = json.loads(fetch(base + "/repos"))
        repos = repos.get("repos", []) if isinstance(repos, dict) else repos
        name = next((r["name"] for r in repos if same_path(r.get("path", ""), root)), None)
        if not name: raise RuntimeError(f"no gitnexus index for {root}; pass --reindex")
        return fetch(base + "/graph?repo=" + urllib.request.quote(name))
    finally:
        child.terminate()
        try: child.wait(10)
        except Exception: child.kill()


def write_snapshot(path, body):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp"); tmp.write_bytes(body); os.replace(tmp, path)


def snapshot(conn, db_path, project, reindex=False, **kw):
    """Build and write the snapshot; returns (path, graph) for reporting."""
    body = run_gitnexus(project_root(conn, project), reindex, **kw)
    g = json.loads(body)
    if not isinstance(g, dict) or "nodes" not in g or "relationships" not in g: raise RuntimeError("unexpected gitnexus graph shape")
    p = snapshot_path(db_path, project); write_snapshot(p, body); return p, g


def load_snapshot(db_path, project):
    """Parsed snapshot; FileNotFoundError when none."""
    return json.loads(snapshot_path(db_path, project).read_bytes())
