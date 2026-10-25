import json, threading, time, urllib.error, urllib.request
import pytest
from strata import db, server


@pytest.fixture
def srv(tmp_path):
    p = tmp_path / "t.db"; c = db.init(str(p)); db.add_project(c, "g", "Group"); c.close()
    s = server.make_server(p, None, 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{s.server_address[1]}", p, tmp_path
    s.shutdown(); s.server_close()


def tok(hp):
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: return json.load(r)["token"]


def call(hp, body, **hdr):
    h = {"X-Strata-Edit": "1", "Content-Type": "application/json", "X-Strata-Token": tok(hp), **hdr}
    h = {k: v for k, v in h.items() if v is not None}
    try:
        with urllib.request.urlopen(urllib.request.Request("http://" + hp + "/api/project", json.dumps(body).encode(), h, method="POST")) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_add_then_delete_with_audit(srv):
    hp, p, tmp = srv
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": str(tmp), "docs_dir": "docs", "parent": "g"})[0] == 200
    c = db.connect(p)
    row = c.execute("SELECT * FROM project WHERE id='app'").fetchone()
    assert row["parent"] == "g" and row["docs_dir"] == str(tmp / "docs")
    db.add_item(c, "app", "task", "t1")
    assert call(hp, {"op": "delete", "id": "app", "confirm": "nope"})[0] == 400
    assert call(hp, {"op": "delete", "id": "app", "confirm": "app"})[0] == 200
    assert c.execute("SELECT count(*) FROM project WHERE id='app'").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM item WHERE project='app'").fetchone()[0] == 0
    tools = [r[0] for r in c.execute("SELECT tool FROM audit WHERE project='app' ORDER BY id")]
    assert tools[0] == "project.add" and tools[-1] == "project.delete"


def test_validation_and_guards(srv):
    hp, p, tmp = srv
    for bad in ({"op": "add", "id": "Bad Id", "name": "x"}, {"op": "add", "id": "g", "name": "dup"}, {"op": "add", "id": "x", "name": ""},
                {"op": "add", "id": "x", "name": "x", "parent": "zzz"}, {"op": "add", "id": "x", "name": "x", "root": "/no/such/dir"}, {"op": "boom"}):
        assert call(hp, bad)[0] == 400, bad
    assert call(hp, {"op": "delete", "id": "ghost", "confirm": "ghost"})[0] == 404
    assert call(hp, {"op": "add", "id": "kid", "name": "Kid", "parent": "g"})[0] == 200
    st, r = call(hp, {"op": "delete", "id": "g", "confirm": "g"})
    assert st == 400 and "sub-projects" in r["error"]
    assert call(hp, {"op": "add", "id": "y", "name": "y"}, **{"X-Strata-Edit": None})[0] == 403
    assert call(hp, {"op": "add", "id": "y", "name": "y"}, Origin="http://evil.test")[0] == 403


def test_token_and_edit(srv):
    hp, p, tmp = srv
    assert call(hp, {"op": "add", "id": "a", "name": "A"}, **{"X-Strata-Token": None})[0] == 403
    assert call(hp, {"op": "add", "id": "a", "name": "A"}, **{"X-Strata-Token": "wrong"})[0] == 403
    assert call(hp, {"op": "add", "id": "a", "name": "A"})[0] == 200
    assert call(hp, {"op": "edit", "id": "a", "name": "A2", "description": "d", "parent": "g"})[0] == 200
    r = db.connect(p).execute("SELECT name,description,parent FROM project WHERE id='a'").fetchone()
    assert tuple(r) == ("A2", "d", "g")
    assert call(hp, {"op": "edit", "id": "a", "name": ""})[0] == 400
    assert call(hp, {"op": "edit", "id": "zz", "name": "x"})[0] == 404
    assert call(hp, {"op": "edit", "name": "x"})[0] == 400


GRAPH = json.dumps({"nodes": [{"id": 1}], "relationships": []}).encode()


@pytest.fixture
def mk(tmp_path):
    ss = []
    def make(build):
        p = tmp_path / "t.db"; db.init(str(p)).close()
        s = server.make_server(p, None, 0, build=build); ss.append(s)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        return f"127.0.0.1:{s.server_address[1]}", tmp_path
    yield make
    for s in ss: s.shutdown(); s.server_close()


def get(hp, path):
    try:
        with urllib.request.urlopen(f"http://{hp}{path}") as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def wait_for(f):
    for _ in range(200):
        if f(): return
        time.sleep(0.02)
    raise AssertionError("timeout")


def repo(tmp, name="app"):
    r = tmp / name; r.mkdir(); (r / "a.py").write_text("x=1\n"); return str(r)


def test_setup_background_build(mk):
    go = threading.Event(); seen = []
    def build(root, reindex=False): seen.append((root, reindex)); go.wait(5); return GRAPH
    hp, tmp = mk(build); root = repo(tmp)
    st, r = call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})
    assert st == 200 and r["id"] == "app" and r["steps"][-1] == {"step": "codemap", "status": "started", "detail": "building in the background"}
    assert get(hp, "/api/codemap?project=app") == (404, {"error": "building", "building": True})
    assert get(hp, "/api/projects")[0] == 200 and get(hp, "/api/version")[0] == 200  # server stays responsive while building
    go.set(); wait_for(lambda: get(hp, "/api/codemap?project=app")[0] == 200)
    assert seen == [(root, True)]


def test_setup_build_failure_remembered(mk):
    def build(root, reindex=False): raise RuntimeError("gitnexus exploded")
    hp, tmp = mk(build)
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": repo(tmp), "setup": True})[0] == 200
    wait_for(lambda: get(hp, "/api/codemap?project=app")[1].get("building") is False)
    assert get(hp, "/api/codemap?project=app") == (404, {"error": "gitnexus exploded", "building": False})


def test_setup_bad_graph_and_no_code(mk):
    hp, tmp = mk(lambda root, reindex=False: b"[]")
    call(hp, {"op": "add", "id": "app", "name": "App", "root": repo(tmp), "setup": True})
    wait_for(lambda: get(hp, "/api/codemap?project=app")[1].get("building") is False)
    assert "graph shape" in get(hp, "/api/codemap?project=app")[1]["error"]
    empty = tmp / "empty"; empty.mkdir()
    st, r = call(hp, {"op": "add", "id": "e", "name": "E", "root": str(empty), "setup": True})
    assert st == 200 and r["steps"][-1]["status"] == "skipped"


def test_setup_validation(mk):
    hp, tmp = mk(lambda root, reindex=False: GRAPH); root = repo(tmp)
    for bad in ({"setup": "yes"}, {"setup": 1}, {"setup": True}, {"setup": True, "root": root, "docs_dir": "/etc/x"},
                {"setup": True, "root": root, "docs_dir": "../out"}, {"setup": True, "root": root, "id": 5}):
        assert call(hp, {"op": "add", "id": "app", "name": "App", **bad})[0] == 400, bad
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "docs_dir": "d", "setup": True})[0] == 200
