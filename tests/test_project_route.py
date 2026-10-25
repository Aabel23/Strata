import json, threading, time, urllib.error, urllib.request
import pytest
from strata import codemap, db, server


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
    def build(root, reindex=False, cancel=None): seen.append((root, reindex)); go.wait(5); return GRAPH
    hp, tmp = mk(build); root = repo(tmp)
    st, r = call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})
    assert st == 200 and r["id"] == "app" and r["steps"][-1] == {"step": "codemap", "status": "started", "detail": "building in the background"}
    assert get(hp, "/api/codemap?project=app") == (404, {"error": "building", "building": True})
    assert get(hp, "/api/projects")[0] == 200 and get(hp, "/api/version")[0] == 200  # server stays responsive while building
    st, again = call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})
    assert st == 200 and again["steps"][-1]["status"] == "started" and len(seen) == 1
    go.set(); wait_for(lambda: get(hp, "/api/codemap?project=app")[0] == 200)
    assert seen == [(root, True)]


def test_setup_build_failure_remembered(mk):
    def build(root, reindex=False, cancel=None): raise RuntimeError("gitnexus exploded")
    hp, tmp = mk(build)
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": repo(tmp), "setup": True})[0] == 200
    wait_for(lambda: get(hp, "/api/codemap?project=app")[1].get("building") is False)
    assert get(hp, "/api/codemap?project=app") == (404, {"error": "gitnexus exploded", "building": False})


def test_setup_bad_graph_and_no_code(mk):
    hp, tmp = mk(lambda root, reindex=False, cancel=None: b"[]")
    call(hp, {"op": "add", "id": "app", "name": "App", "root": repo(tmp), "setup": True})
    wait_for(lambda: get(hp, "/api/codemap?project=app")[1].get("building") is False)
    assert "graph shape" in get(hp, "/api/codemap?project=app")[1]["error"]
    empty = tmp / "empty"; empty.mkdir()
    st, r = call(hp, {"op": "add", "id": "e", "name": "E", "root": str(empty), "setup": True})
    assert st == 200 and r["steps"][-1]["status"] == "skipped"


def test_setup_validation(mk):
    hp, tmp = mk(lambda root, reindex=False, cancel=None: GRAPH); root = repo(tmp)
    for bad in ({"setup": "yes"}, {"setup": 1}, {"setup": True}, {"setup": True, "root": root, "docs_dir": "/etc/x"},
                {"setup": True, "root": root, "docs_dir": "../out"}, {"setup": True, "root": root, "id": 5}):
        assert call(hp, {"op": "add", "id": "app", "name": "App", **bad})[0] == 400, bad
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "docs_dir": "d", "setup": True})[0] == 200


def test_builds_are_globally_limited_across_servers(mk):
    gate = threading.Event(); lock = threading.Lock(); active = maximum = 0; started = []
    def build(root, reindex=False, cancel=None):
        nonlocal active, maximum
        with lock:
            active += 1; maximum = max(maximum, active); started.append(root)
        while not gate.wait(0.01) and not cancel.is_set(): pass
        with lock: active -= 1
        return GRAPH
    hp1, tmp = mk(build); hp2, _ = mk(build)
    root1, root2 = repo(tmp, "one"), repo(tmp, "two")
    assert call(hp1, {"op": "add", "id": "one", "name": "One", "root": root1, "setup": True})[0] == 200
    wait_for(lambda: len(started) == 1)
    assert call(hp2, {"op": "add", "id": "two", "name": "Two", "root": root2, "setup": True})[0] == 200
    time.sleep(0.1)
    assert len(started) == 1 and maximum == 1
    assert get(hp1, "/api/projects")[0] == get(hp2, "/api/projects")[0] == 200
    gate.set(); wait_for(lambda: len(started) == 2)
    wait_for(lambda: get(hp1, "/api/codemap?project=one")[0] == 200 and get(hp2, "/api/codemap?project=two")[0] == 200)
    assert set(started) == {root1, root2} and maximum == 1


def test_same_project_is_deduped_across_listeners_and_owner_shutdown_isolated(tmp_path):
    started = threading.Event(); release = threading.Event(); cancelled = threading.Event(); other_calls = []
    def owner_build(root, reindex=False, cancel=None):
        started.set()
        while not release.wait(0.01) and not cancel.is_set(): pass
        cancelled.set() if cancel.is_set() else None
        return GRAPH
    def other_build(root, reindex=False, cancel=None): other_calls.append(root); return GRAPH
    p = tmp_path / "t.db"; db.init(str(p)).close()
    owner = server.make_server(p, None, 0, build=owner_build)
    other = server.make_server(p, None, 0, build=other_build)
    threading.Thread(target=owner.serve_forever, daemon=True).start()
    threading.Thread(target=other.serve_forever, daemon=True).start()
    hp_owner = f"127.0.0.1:{owner.server_address[1]}"; hp_other = f"127.0.0.1:{other.server_address[1]}"
    other_closed = False
    try:
        root = repo(tmp_path)
        assert call(hp_owner, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})[0] == 200
        assert started.wait(2)
        status, response = call(hp_other, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})
        assert status == 200 and response["steps"][-1]["status"] == "started"
        assert get(hp_owner, "/api/codemap?project=app") == (404, {"error": "building", "building": True})
        assert get(hp_other, "/api/codemap?project=app") == (404, {"error": "building", "building": True})
        other.shutdown(); other.server_close(); other_closed = True
        assert not cancelled.is_set()
        release.set()
        wait_for(lambda: get(hp_owner, "/api/codemap?project=app")[0] == 200)
        time.sleep(0.1)
        assert not cancelled.is_set() and other_calls == []
    finally:
        release.set()
        if not other_closed: other.shutdown(); other.server_close()
        owner.shutdown(); owner.server_close()


def test_old_snapshot_remains_visible_during_and_after_failed_rebuild(mk):
    gate = threading.Event(); started = threading.Event(); finished = threading.Event()
    old = json.dumps({"nodes": [{"id": "old"}], "relationships": []}).encode()
    def build(root, reindex=False, cancel=None):
        started.set(); gate.wait(5); finished.set(); raise RuntimeError("rebuild failed")
    hp, tmp = mk(build); root = repo(tmp)
    path = codemap.snapshot_path(tmp / "t.db", "app")
    codemap.write_snapshot(path, old)
    assert call(hp, {"op": "add", "id": "app", "name": "App", "root": root, "setup": True})[0] == 200
    assert started.wait(2)
    assert get(hp, "/api/codemap?project=app") == (200, json.loads(old))
    gate.set(); assert finished.wait(2)
    wait_for(lambda: get(hp, "/api/codemap?project=app")[0] == 200)
    assert get(hp, "/api/codemap?project=app") == (200, json.loads(old))


def test_slow_code_walk_does_not_hold_database_lock(mk, monkeypatch):
    entered = threading.Event(); release = threading.Event(); result = []
    def has_code(root): entered.set(); release.wait(5); return False
    monkeypatch.setattr(server.service, "has_code", has_code)
    hp, tmp = mk(lambda root, reindex=False, cancel=None: GRAPH)
    request = threading.Thread(target=lambda: result.append(call(hp, {"op": "add", "id": "app", "name": "App", "root": repo(tmp), "setup": True})))
    request.start()
    try:
        assert entered.wait(2)
        assert get(hp, "/api/projects")[0] == 200
    finally:
        release.set(); request.join(2)
    assert result and result[0][0] == 200


def test_shutdown_cancels_active_and_queued_builds(tmp_path):
    started = threading.Event(); calls = []
    def build(root, reindex=False, cancel=None):
        calls.append(root); started.set(); cancel.wait(5); return GRAPH
    p = tmp_path / "t.db"; db.init(str(p)).close()
    s = server.make_server(p, None, 0, build=build)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    hp = f"127.0.0.1:{s.server_address[1]}"
    try:
        assert call(hp, {"op": "add", "id": "one", "name": "One", "root": repo(tmp_path, "one"), "setup": True})[0] == 200
        assert started.wait(2)
        assert call(hp, {"op": "add", "id": "two", "name": "Two", "root": repo(tmp_path, "two"), "setup": True})[0] == 200
        assert get(hp, "/api/codemap?project=two") == (404, {"error": "building", "building": True})
    finally:
        s.shutdown(); s.server_close()
    assert calls == [str(tmp_path / "one")]
    assert not codemap.snapshot_path(p, "one").exists()
    assert not codemap.snapshot_path(p, "two").exists()
