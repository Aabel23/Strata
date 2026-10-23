import shutil
import pytest
from strata import c4_edit, c4_layered as L, db
from conftest import FIX


@pytest.fixture
def env(tmp_path):
    d = tmp_path / "c4"; shutil.copytree(FIX, d)
    (tmp_path / "src").mkdir()
    (d / "map.yaml").write_text((d / "map.yaml").read_text().replace("root: .", "root: .."))
    c = db.init(str(tmp_path / "t.db")); db.add_project(c, "p", "P", root=str(tmp_path))
    L.import_dir(c, d, "p")
    return c, d


def snap(d): return {p.relative_to(d): p.read_text() for p in d.rglob("*.yaml")}
def ids(c, t): return {r[0] for r in c.execute(f"SELECT id FROM c4_{t} WHERE project='p'")}
def ap(c, **op): return c4_edit.apply(c, "p", op)


def test_add_update_object(env):
    c, d = env
    r = ap(c, op="add_object", name="Cache Ünit", kind="component", parent="cloud", tags=["x"])
    assert r["ok"] and "map.yaml" in r["changed"] and "cache_unit" in ids(c, "object")
    assert ap(c, op="add_object", name="Cache Ünit", kind="store")["ok"] and "cache_unit_2" in ids(c, "object")
    ap(c, op="update_object", id="cache_unit", set={"summary": "fast", "parent": None, "kind": "store"})
    o = next(o for o in L.read_model(c, "p")["objects"] if o["id"] == "cache_unit")
    assert o["description"] == "fast" and o["type"] == "store" and "parent" not in o
    assert c.execute("SELECT count(*) FROM audit WHERE tool='c4-import'").fetchone()[0] == 4


def test_links(env):
    c, d = env
    ap(c, op="add_link", **{"from": "user", "to": "db"}, name="Peek", detail="relay_command.send")
    assert "user_db" in ids(c, "connection")
    ap(c, op="update_link", id="user_db", set={"name": "Look", "detail": None, "to": "relay"})
    x = next(x for x in L.read_model(c, "p")["connections"] if x["id"] == "user_db")
    assert x["name"] == "Look" and x["to"] == "relay" and "detail" not in x
    ap(c, op="delete_link", id="user_db")
    assert "user_db" not in ids(c, "connection")


def test_delete_object_cascade_removes_behavior(env):
    c, d = env
    with pytest.raises(ValueError, match="children|links"): ap(c, op="delete_object", id="cloud")
    with pytest.raises(ValueError, match="send_command"): ap(c, op="delete_object", id="cloud", cascade=True)
    ap(c, op="add_object", id="tmp", name="Tmp", kind="component", parent="db")
    ap(c, op="add_link", id="tmp_l", **{"from": "tmp", "to": "db"}, name="x")
    ap(c, op="delete_object", id="tmp", cascade=True)
    assert "tmp" not in ids(c, "object") and "tmp_l" not in ids(c, "connection")


def test_delete_object_drops_behavior_file(env):
    c, d = env
    (d / "flows/send_command.yaml").unlink(); L.import_dir(c, d, "p")
    r = ap(c, op="delete_object", id="relay", cascade=True)
    assert "behavior/relay.yaml" in r["changed"] and not (d / "behavior/relay.yaml").exists()
    assert "relay" not in ids(c, "object") and "relay_db" not in ids(c, "connection")


@pytest.mark.parametrize("op,msg", [
    ({"op": "nope"}, "unknown op"),
    ({"op": "update_object", "id": "zz", "set": {}}, "unknown object"),
    ({"op": "add_object", "id": "db", "name": "X", "kind": "store"}, "duplicate"),
    ({"op": "add_object", "name": "X", "kind": "file"}, "kind"),
    ({"op": "add_object", "name": "X", "kind": "store", "parent": "zz"}, "unknown parent"),
    ({"op": "add_object", "name": "X", "kind": "store", "bogus": 1}, "unknown keys"),
    ({"op": "add_object", "name": 5, "kind": "store"}, "must be a string"),
    ({"op": "update_object", "id": "db", "set": {"id": "db2"}}, "renaming"),
    ({"op": "update_object", "id": "cloud", "set": {"parent": "relay"}}, "errors"),
    ({"op": "delete_object", "id": "cloud"}, "cascade"),
    ({"op": "delete_object", "id": "app", "cascade": True}, "send_command"),
    ({"op": "delete_link", "id": "app_cmd"}, "send_command"),
    ({"op": "add_link", "from": "app", "to": "zz", "name": "x"}, "unknown object"),
    ({"op": "add_link", "from": "app", "to": "db", "name": "x", "detail": "no.such"}, "unknown contract"),
    ({"op": "add_link", "id": "app_cmd", "from": "app", "to": "db", "name": "x"}, "duplicate"),
    ({"op": "update_object", "id": "db", "set": {"status": "weird"}}, "errors"),
])
def test_negatives_leave_everything_unchanged(env, op, msg):
    c, d = env
    s, counts = snap(d), L._counts(c, "p")
    with pytest.raises(ValueError, match=msg): c4_edit.apply(c, "p", op)
    assert snap(d) == s and L._counts(c, "p") == counts
    assert c.execute("SELECT count(*) FROM audit WHERE tool='c4-import'").fetchone()[0] == 1


def test_dropped_task_link_needs_yes(env):
    c, d = env
    (d / "flows/send_command.yaml").unlink(); L.import_dir(c, d, "p")
    t = db.add_item(c, "p", "task", "T")
    c.execute("INSERT INTO c4_link VALUES('p','db','item',?)", (t,)); c.commit()
    s = snap(d)
    with pytest.raises(ValueError, match="task links"): ap(c, op="delete_object", id="db", cascade=True)
    assert snap(d) == s
    assert ap_yes(c)["ok"] and "db" not in ids(c, "object")


def ap_yes(c): return c4_edit.apply(c, "p", {"op": "delete_object", "id": "db", "cascade": True}, yes=True)


def test_import_failure_restores_folder(env, monkeypatch):
    c, d = env
    s = L.load(d)[0]
    def boom(*a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(L, "import_dir", boom)
    with pytest.raises(RuntimeError): ap(c, op="add_object", name="New", kind="store")
    assert L.load(d)[0] == s and "new" not in ids(c, "object")


def test_unknown_project(env):
    with pytest.raises(KeyError): c4_edit.apply(env[0], "zz", {"op": "add_object"})
