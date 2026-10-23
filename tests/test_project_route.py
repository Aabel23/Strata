import json, threading, urllib.error, urllib.request
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
