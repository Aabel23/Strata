import json, threading, urllib.error, urllib.request
import pytest
from strata import db, server


@pytest.fixture
def srv(tmp_path):
    p = tmp_path / "t.db"; c = db.init(str(p)); db.add_project(c, "a", "A"); c.close()
    s = server.make_server(p, None, 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{s.server_address[1]}", p
    s.shutdown(); s.server_close()


def call(hp, body, path="/api/item?project=a", **hdr):
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: tok = json.load(r)["token"]
    h = {"X-Strata-Edit": "1", "Content-Type": "application/json", "X-Strata-Token": tok, **hdr}
    h = {k: v for k, v in h.items() if v is not None}
    try:
        with urllib.request.urlopen(urllib.request.Request("http://" + hp + path, json.dumps(body).encode(), h, method="POST")) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_guards(srv):
    hp, _ = srv
    add = {"op": "add", "kind": "task", "title": "t"}
    assert call(hp, add, **{"X-Strata-Token": None})[0] == 403
    assert call(hp, add, **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, add, Origin="http://evil.test")[0] == 403
    assert call(hp, add, **{"X-Strata-Edit": None})[0] == 403
    assert call(hp, add)[0] == 200
    with urllib.request.urlopen(f"http://{hp}/api/items?project=a") as r: assert len(json.load(r)) == 1


def test_add_edit_status_audit(srv):
    hp, p = srv
    st, r = call(hp, {"op": "add", "kind": "issue", "title": "bug", "body": "b", "priority": "high", "spec": {"goal": "g"}})
    assert st == 200; i = r["id"]
    c = db.connect(p); row = c.execute("SELECT * FROM item WHERE id=?", (i,)).fetchone()
    assert row["label"] == "issue" and row["status"] == "approved" and row["priority"] == "high" and json.loads(row["spec"]) == {"goal": "g"}
    assert call(hp, {"op": "edit", "id": i, "title": "bug2", "body": "bb", "spec": {"goal": "g2", "scope": {"touch": ["x"]}}})[0] == 200
    assert call(hp, {"op": "edit", "id": i, "status": "doing"})[0] == 200
    row = c.execute("SELECT * FROM item WHERE id=?", (i,)).fetchone()
    assert (row["title"], row["body"], row["status"]) == ("bug2", "bb", "doing") and json.loads(row["spec"])["goal"] == "g2"
    assert {"item.add", "item.edit", "item.transition"} <= {x[0] for x in c.execute("SELECT tool FROM audit")}
    assert call(hp, {"op": "edit", "id": i, "status": "proposed"})[0] == 403  # illegal transition is denied by the service


def test_validation(srv):
    hp, _ = srv
    for bad in ({"op": "boom"}, {"op": "add", "kind": "nope", "title": "t"}, {"op": "add", "kind": "task", "title": " "}, {"op": "add", "kind": "task"},
                {"op": "add", "kind": "task", "title": "t", "status": "x"}, {"op": "add", "kind": "task", "title": "t", "spec": [1]},
                {"op": "edit", "id": 1}, {"op": "edit", "id": "1", "title": "x"}, {"op": "dep_add", "id": 1}):
        assert call(hp, bad)[0] == 400, bad
    assert call(hp, {"op": "add", "kind": "task", "title": "t"}, path="/api/item?project=zz")[0] == 404
    assert call(hp, {"op": "edit", "id": 99, "title": "x"})[0] == 404
    assert call(hp, {"op": "delete", "id": 99})[0] == 404


def test_delete_and_deps(srv):
    hp, p = srv
    a, b, c_ = (call(hp, {"op": "add", "kind": "task", "title": t})[1]["id"] for t in "abc")
    assert call(hp, {"op": "dep_add", "id": b, "depends_on": a})[0] == 200
    assert call(hp, {"op": "dep_add", "id": c_, "depends_on": b})[0] == 200
    assert call(hp, {"op": "dep_add", "id": a, "depends_on": c_})[0] == 400  # cycle
    assert call(hp, {"op": "dep_add", "id": a, "depends_on": a})[0] == 400
    assert call(hp, {"op": "dep_add", "id": a, "depends_on": 999})[0] == 404
    cn = db.connect(p)
    assert cn.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 2
    assert call(hp, {"op": "dep_rm", "id": c_, "depends_on": b})[0] == 200
    assert cn.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 1
    assert call(hp, {"op": "delete", "id": a})[0] == 200
    assert cn.execute("SELECT count(*) FROM item WHERE id=?", (a,)).fetchone()[0] == 0 and cn.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 0
    assert cn.execute("SELECT count(*) FROM audit WHERE tool='item.delete'").fetchone()[0] == 1
