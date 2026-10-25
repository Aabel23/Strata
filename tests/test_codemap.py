import json, threading, urllib.request, urllib.error
import pytest
from conftest import run
from strata import codemap, db, server

G = {"nodes": [{"id": "a"}], "relationships": []}


class Child:
    terminated = False
    def poll(self): return None
    def terminate(self): self.terminated = True
    def wait(self, t=None): pass
    def kill(self): pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(codemap, "gitnexus_cmd", lambda: ["gx"])
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P", root=str(tmp_path)); c.commit()
    return p, c, tmp_path


def fakes(root, repos=None):
    calls, child = [], Child()
    def fetch(url):
        calls.append(url)
        if url.endswith("/health"): return b"{}"
        if url.endswith("/repos"): return json.dumps([{"name": "r", "path": str(root)}] if repos is None else repos).encode()
        return json.dumps(G).encode()
    return calls, child, dict(spawn=lambda cmd: child, run=lambda cmd: calls.append(cmd) or type("R", (), {"returncode": 0})(), fetch=fetch)


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
        assert get("/api/codemap?project=p")[0] == 404
        assert get("/api/codemap")[0] == 400 and get("/api/codemap?project=zz")[0] == 400
        codemap.write_snapshot(codemap.snapshot_path(p, "p"), json.dumps(G).encode())
        st, ct, body = get("/api/codemap?project=p")
        assert st == 200 and ct.startswith("application/json") and body == G
    finally: srv.shutdown(); srv.server_close()
