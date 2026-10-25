import io, json, threading, urllib.request, urllib.error
import pytest
from conftest import run
from strata import codemap, db, server

G = {"nodes": [{"id": "a"}], "relationships": []}


class Child:
    def __init__(self, exit_code=None, wait_log=False): self.exit_code = exit_code; self.wait_log = wait_log; self.output = None; self.stderr = None; self.terminated = False; self.waited = False; self.on_poll = None
    def poll(self):
        if self.on_poll: self.on_poll()
        return self.exit_code
    def terminate(self): self.terminated = True
    def wait(self, t=None):
        self.waited = True
        if self.wait_log: self.output.write(b"written while reaping")
        if getattr(self, "cancel_on_wait", None) is not None: self.cancel_on_wait.set()
    def kill(self): pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(codemap, "gitnexus_cmd", lambda: ["gx"])
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P", root=str(tmp_path)); c.commit()
    return p, c, tmp_path


def fakes(root, repos=None, *, log=b"", analyze_code=0, serve_code=None, health_fail=False, wait_log=False, cancel_on_health=None, cancel_on_analyze_poll=None, cancel_on_wait=None, block_health=None):
    calls, children = [], []
    def fetch(url):
        calls.append(url)
        if url.endswith("/health") and block_health is not None:
            entered, release = block_health; entered.set(); release.wait()
        if url.endswith("/health") and cancel_on_health is not None: cancel_on_health.set()
        if url.endswith("/health") and health_fail: raise OSError("not ready")
        if url.endswith("/health") and serve_code is not None: raise OSError("not ready")
        if url.endswith("/health"): return b"{}"
        if url.endswith("/repos"): return json.dumps([{"name": "r", "path": str(root)}] if repos is None else repos).encode()
        return json.dumps(G).encode()
    def write(stream):
        if stream is not None: stream.write(log)
    def spawn(cmd, stdout=None, stderr=None):
        calls.append(cmd); code = analyze_code if "analyze" in cmd else serve_code
        child = Child(code, wait_log); child.output = stdout; child.stderr = stderr; children.append(child)
        child.cancel_on_wait = cancel_on_wait
        if "analyze" in cmd and cancel_on_analyze_poll is not None: child.on_poll = cancel_on_analyze_poll.set
        write(stdout); return child
    return calls, children, dict(spawn=spawn, fetch=fetch)


def test_snapshot_raw_atomic(env):
    p, c, root = env; calls, children, kw = fakes(root)
    path, g = codemap.snapshot(c, p, "p", **kw)
    assert path == root / "t.codemap" / "p.json" and json.loads(path.read_text()) == G == g
    assert not list(path.parent.glob("*.tmp")) and children[-1].terminated
    assert not any(isinstance(x, list) and "analyze" in x for x in calls) and calls[-1].endswith("/graph?repo=r")


def test_reindex_uses_index_only(env):
    p, c, root = env; calls, _, kw = fakes(root)
    codemap.snapshot(c, p, "p", True, **kw)
    assert calls[0] == ["gx", "analyze", "--index-only", str(root)]


def test_subprocess_output_is_quiet_on_success(env, capsys):
    p, c, root = env; calls, children, kw = fakes(root, log=b"banner\nprogress\n")
    codemap.snapshot(c, p, "p", True, **kw)
    assert capsys.readouterr() == ("", "")
    assert len(children) == 2 and all(x.output is not None and x.stderr == codemap.subprocess.STDOUT for x in children)


def test_analyze_failure_reports_bounded_log_tail(env):
    p, c, root = env
    log = b"x" * 10000 + b"useful failure detail"
    _, _, kw = fakes(root, log=log, analyze_code=1)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", True, **kw)
    message = str(exc.value)
    assert "gitnexus analyze --index-only failed" in message
    assert "useful failure detail" in message
    assert "x" * 5000 not in message


def test_serve_startup_failure_reports_log_tail_and_terminates(env):
    p, c, root = env
    calls, children, kw = fakes(root, log=b"serve failed early", serve_code=1, wait_log=True)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", **kw)
    assert "serve exited during startup" in str(exc.value) and "serve failed early" in str(exc.value)
    assert "written while reaping" in str(exc.value)
    assert children[-1].terminated and children[-1].waited


def test_serve_health_failure_reports_log_tail(env):
    p, c, root = env
    _, children, kw = fakes(root, log=b"health diagnostic", health_fail=True)
    with pytest.raises(RuntimeError) as exc:
        codemap.snapshot(c, p, "p", wait=0, **kw)
    assert "not healthy in 0s" in str(exc.value) and "health diagnostic" in str(exc.value)
    assert children[-1].terminated


def test_analyze_timeout_stops_and_reaps_child_without_snapshot(env):
    p, c, root = env
    _, children, kw = fakes(root, analyze_code=None)
    with pytest.raises(RuntimeError, match="timed out during analyze"):
        codemap.snapshot(c, p, "p", reindex=True, timeout=0.02, **kw)
    assert children[0].terminated and children[0].waited
    assert not codemap.snapshot_path(p, "p").exists()


def test_analyze_cancellation_stops_and_reaps_child(env):
    p, c, root = env; cancel = threading.Event()
    _, children, kw = fakes(root, analyze_code=None, cancel_on_analyze_poll=cancel)
    with pytest.raises(RuntimeError, match="cancelled during analyze"):
        codemap.snapshot(c, p, "p", reindex=True, cancel=cancel, **kw)
    assert children[0].terminated and children[0].waited
    assert not codemap.snapshot_path(p, "p").exists()


def test_serve_timeout_stops_child_without_snapshot(env):
    p, c, root = env
    _, children, kw = fakes(root, health_fail=True)
    with pytest.raises(RuntimeError, match="timed out during serve health check"):
        codemap.snapshot(c, p, "p", timeout=0.02, **kw)
    assert children[-1].terminated and children[-1].waited
    assert not codemap.snapshot_path(p, "p").exists()


def test_cancellation_during_health_fetch_stops_child_without_snapshot(env):
    p, c, root = env; cancel = threading.Event()
    _, children, kw = fakes(root, cancel_on_health=cancel)
    with pytest.raises(RuntimeError, match="cancelled during serve health check"):
        codemap.snapshot(c, p, "p", cancel=cancel, **kw)
    assert children[-1].terminated and children[-1].waited
    assert not codemap.snapshot_path(p, "p").exists()


def test_cancellation_interrupts_wait_for_blocked_health_fetch(env):
    p, c, root = env; cancel = threading.Event(); entered = threading.Event(); release = threading.Event()
    _, children, kw = fakes(root, block_health=(entered, release))
    timer = threading.Timer(0.05, cancel.set); timer.start()
    try:
        with pytest.raises(RuntimeError, match="cancelled during serve health check"):
            codemap.snapshot(c, p, "p", cancel=cancel, timeout=2, **kw)
        assert entered.is_set() and children[-1].terminated and children[-1].waited
        assert not codemap.snapshot_path(p, "p").exists()
    finally:
        release.set(); timer.cancel(); timer.join()


def test_cancellation_during_serve_cleanup_prevents_snapshot(env):
    p, c, root = env; cancel = threading.Event()
    _, children, kw = fakes(root, cancel_on_wait=cancel)
    with pytest.raises(RuntimeError, match="cancelled during serve cleanup") as exc:
        codemap.snapshot(c, p, "p", cancel=cancel, **kw)
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert children[-1].terminated and children[-1].waited
    assert not codemap.snapshot_path(p, "p").exists()


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
    _, children, kw = fakes(root, repos=[])
    with pytest.raises(RuntimeError, match="--reindex"): codemap.snapshot(c, p, "p", **kw)
    assert children[-1].terminated and not (root / "t.codemap" / "p.json").exists()


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
