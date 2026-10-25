import io, json, threading, urllib.request, urllib.error
import pytest
from conftest import run
from strata import codemap, db, server

G = {"nodes": [{"id": "a"}], "relationships": []}


class Child:
    terminated = False
    def __init__(self, exit_code=None, wait_log=False): self.exit_code = exit_code; self.wait_log = wait_log; self.output = None
    def poll(self): return self.exit_code
    def terminate(self): self.terminated = True
    def wait(self, t=None):
        if self.wait_log: self.output.write(b"written while reaping")
    def kill(self): pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(codemap, "gitnexus_cmd", lambda: ["gx"])
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P", root=str(tmp_path)); c.commit()
    return p, c, tmp_path


def fakes(root, repos=None, *, log=b"", run_code=0, serve_code=None, health_fail=False, wait_log=False):
    calls, child = [], Child(serve_code, wait_log)
    def fetch(url):
        calls.append(url)
        if url.endswith("/health") and health_fail: raise OSError("not ready")
        if url.endswith("/health") and serve_code is not None: raise OSError("not ready")
        if url.endswith("/health"): return b"{}"
        if url.endswith("/repos"): return json.dumps([{"name": "r", "path": str(root)}] if repos is None else repos).encode()
        return json.dumps(G).encode()
    def write(stream):
        if stream is not None: stream.write(log)
    def spawn(cmd, stdout=None, stderr=None):
        calls.append((cmd, stdout, stderr)); child.output = stdout; write(stdout); return child
    def run(cmd, stdout=None, stderr=None):
        calls.append(cmd); write(stdout); return type("R", (), {"returncode": run_code})()
    return calls, child, dict(spawn=spawn, run=run, fetch=fetch)


def test_snapshot_raw_atomic(env):
    p, c, root = env; calls, child, kw = fakes(root)
    path, g = codemap.snapshot(c, p, "p", **kw)
    assert path == root / "t.codemap" / "p.json" and json.loads(path.read_text()) == G == g
    assert not list(path.parent.glob("*.tmp")) and child.terminated
    assert not any(isinstance(x, list) for x in calls) and calls[-1].endswith("/graph?repo=r")


def test_reindex_uses_index_only(env):
    p, c, root = env; calls, _, kw = fakes(root)
    codemap.snapshot(c, p, "p", True, **kw)
    assert calls[0] == ["gx", "analyze", "--index-only", str(root)]


def test_subprocess_output_is_quiet_on_success(env, capsys):
    p, c, root = env; calls, _, kw = fakes(root, log=b"banner\nprogress\n")
    codemap.snapshot(c, p, "p", True, **kw)
    assert capsys.readouterr() == ("", "")
    serve = next(x for x in calls if isinstance(x, tuple))
    assert serve[1] is not None and serve[2] == codemap.subprocess.STDOUT


def test_analyze_failure_reports_bounded_log_tail(env):
    p, c, root = env
    log = b"x" * 10000 + b"useful failure detail"
    _, _, kw = fakes(root, log=log, run_code=1)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", True, **kw)
    message = str(exc.value)
    assert "gitnexus analyze --index-only failed" in message
    assert "useful failure detail" in message
    assert "x" * 5000 not in message


def test_serve_startup_failure_reports_log_tail_and_terminates(env):
    p, c, root = env
    calls, child, kw = fakes(root, log=b"serve failed early", serve_code=1, wait_log=True)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", **kw)
    assert "serve exited during startup" in str(exc.value) and "serve failed early" in str(exc.value)
    assert "written while reaping" in str(exc.value)
    assert child.terminated


def test_serve_health_failure_reports_log_tail(env):
    p, c, root = env
    _, child, kw = fakes(root, log=b"health diagnostic", health_fail=True)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", wait=0, **kw)
    assert "not healthy in 0s" in str(exc.value) and "health diagnostic" in str(exc.value)
    assert child.terminated


def test_failure_tail_read_is_explicitly_bounded():
    class ReadSpy(io.BytesIO):
        size = None
        def read(self, size=-1):
            self.size = size
            return super().read(size)
    log = ReadSpy(b"x" * 10000)
    codemap._failure("failed", log)
    assert log.size == 4096


def test_errors(env):
    p, c, root = env
    with pytest.raises(KeyError): codemap.snapshot(c, p, "nope", **fakes(root)[2])
    _, child, kw = fakes(root, repos=[])
    with pytest.raises(RuntimeError, match="--reindex"): codemap.snapshot(c, p, "p", **kw)
    assert child.terminated and not (root / "t.codemap" / "p.json").exists()


def test_cli_unknown_project(env):
    rc, out = run(env[0], "code", "snapshot", "--project", "zz")
    assert rc == 1 and "unknown project" in out


def test_route(env):
    p, c, root = env
    srv = server.make_server(p, None, 0); threading.Thread(target=srv.serve_forever, daemon=True).start()
    def get(path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}{path}") as r: return r.status, r.headers["Content-Type"], json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, "", json.loads(e.read())
    try:
        st, _, body = get("/api/codemap?project=p")
        assert st == 404 and body["error"] == "no code map" and body["empty"] is True and "root" in body
        assert get("/api/codemap")[0] == 400 and get("/api/codemap?project=zz")[0] == 400
        codemap.write_snapshot(codemap.snapshot_path(p, "p"), json.dumps(G).encode())
        st, ct, body = get("/api/codemap?project=p")
        assert st == 200 and ct.startswith("application/json") and body == G
    finally: srv.shutdown(); srv.server_close()
