"""Designer support in the C4 edit path: saved card positions (layout.yaml), flow edits, batches, starting a map, the check route."""
import json, shutil, threading, urllib.request, urllib.error
import pytest, yaml
from strata import c4_edit as E, c4_layered as L, db, server
from conftest import FIX


@pytest.fixture
def env(tmp_path):
    d = tmp_path / "c4"; shutil.copytree(FIX, d); (tmp_path / "src").mkdir(); (tmp_path / "empty").mkdir()
    (d / "map.yaml").write_text((d / "map.yaml").read_text().replace("root: .", "root: .."))
    p = str(tmp_path / "t.db"); c = db.init(p)
    db.add_project(c, "p", "P", root=str(tmp_path)); db.add_project(c, "new", "New One", root=str(tmp_path / "empty"))
    L.import_dir(c, d, "p")
    return c, d, p


def ids(c): return {o["id"] for o in L.read_model(c, "p")["objects"]}


def test_positions_round_trip_and_follow_deleted_objects(env):
    c, d, _ = env
    a, b = sorted(ids(c))[:2]
    r = E.apply(c, "p", {"op": "set_positions", "view": "_root", "positions": {a: [10.4, 20], b: [300, -40]}})
    assert r["changed"] == ["layout.yaml"] and L.read_model(c, "p")["positions"] == {"_root": {a: [10, 20], b: [300, -40]}}
    assert yaml.safe_load((d / "layout.yaml").read_text()) == {"views": {"_root": {a: [10, 20], b: [300, -40]}}}
    L.import_dir(c, d, "p")  # a plain re-import keeps what the file says
    assert L.read_model(c, "p")["positions"]["_root"][b] == [300, -40]
    E.apply(c, "p", {"op": "set_positions", "view": "_root", "positions": {a: None}})
    assert L.read_model(c, "p")["positions"] == {"_root": {b: [300, -40]}}
    for bad in ({"view": "zz", "positions": {}}, {"view": "_root", "positions": {"zz": [1, 2]}}, {"view": "_root", "positions": {b: [1]}}, {"view": "_root", "positions": {b: ["1", 2]}}):
        with pytest.raises(ValueError): E.apply(c, "p", {"op": "set_positions", **bad})
    E.apply(c, "p", {"op": "add_object", "id": "tmp1", "name": "Tmp", "kind": "system"})
    E.apply(c, "p", {"op": "set_positions", "view": "_root", "positions": {"tmp1": [5, 5]}})
    E.apply(c, "p", {"op": "delete_object", "id": "tmp1"})
    assert "tmp1" not in yaml.safe_load((d / "layout.yaml").read_text())["views"]["_root"]
    E.apply(c, "p", {"op": "set_positions", "view": "_root", "positions": {b: None}})
    assert not (d / "layout.yaml").exists() and L.read_model(c, "p")["positions"] == {}


def test_flow_ops(env):
    c, d, _ = env
    m = L.read_model(c, "p"); link, obj = m["connections"][0]["id"], m["objects"][0]["id"]
    E.apply(c, "p", {"op": "add_flow", "name": "Place an order", "steps": [{"link": link, "text": "go"}, {"at": obj}]})
    f = next(x for x in L.read_model(c, "p")["flows"] if x["id"] == "place_an_order")
    assert f["name"] == "Place an order" and f["steps"] == [{"link": link, "text": "go"}, {"at": obj}] and (d / "flows/place_an_order.yaml").is_file()
    E.apply(c, "p", {"op": "update_flow", "id": "place_an_order", "set": {"name": "Order", "steps": [{"link": link, "reverse": True}, {"link": link, "reverse": False, "text": ""}]}})
    f = next(x for x in L.read_model(c, "p")["flows"] if x["id"] == "place_an_order")
    assert f["name"] == "Order" and f["steps"] == [{"link": link, "reverse": True}, {"link": link}]
    for bad in ([{"link": "zz"}], [{"at": "zz"}], [{"link": link, "at": obj}], [{}], [{"link": link, "nope": 1}], "x"):
        with pytest.raises(ValueError): E.apply(c, "p", {"op": "update_flow", "id": "place_an_order", "set": {"steps": bad}})
    with pytest.raises(ValueError): E.apply(c, "p", {"op": "add_flow", "id": "place_an_order", "name": "dup"})
    with pytest.raises(ValueError): E.apply(c, "p", {"op": "add_flow", "id": "../x", "name": "bad id"})
    E.apply(c, "p", {"op": "delete_flow", "id": "place_an_order"})
    assert not (d / "flows/place_an_order.yaml").exists()
    with pytest.raises(ValueError): E.apply(c, "p", {"op": "delete_flow", "id": "place_an_order"})


def test_batch_is_all_or_nothing(env):
    c, d, _ = env
    before, text = ids(c), (d / "map.yaml").read_text()
    with pytest.raises(ValueError, match=r"batch #2 \(delete_flow\)"):
        E.apply(c, "p", {"op": "batch", "ops": [{"op": "add_object", "id": "b1", "name": "B1", "kind": "system"}, {"op": "delete_flow", "id": "zz"}]})
    assert ids(c) == before and (d / "map.yaml").read_text() == text
    for bad in ([], "x", [{"op": "batch", "ops": []}], [{"op": "nope"}]):
        with pytest.raises(ValueError): E.apply(c, "p", {"op": "batch", "ops": bad})
    E.apply(c, "p", {"op": "batch", "ops": [{"op": "add_object", "id": "b1", "name": "B1", "kind": "system"}, {"op": "add_object", "id": "b2", "name": "B2", "kind": "actor"},
                                            {"op": "add_link", "id": "b2_b1", "from": "b2", "to": "b1", "name": "uses"}, {"op": "set_positions", "view": "_root", "positions": {"b1": [0, 0]}}]})
    assert ids(c) == before | {"b1", "b2"} and L.read_model(c, "p")["positions"]["_root"] == {"b1": [0, 0]}
    assert c.execute("SELECT count(*) FROM audit WHERE tool='c4-import'").fetchone()[0] == 2  # the first import and one for the whole batch


def test_create_map_for_a_project_without_one(env, tmp_path):
    c, _, _ = env
    with pytest.raises(KeyError): E.apply(c, "new", {"op": "add_object", "name": "A", "kind": "system"})
    assert E.apply(c, "new", {"op": "create_map"})["ok"]
    mp = tmp_path / "empty/docs/c4/map.yaml"
    assert yaml.safe_load(mp.read_text()) == {"project": {"id": "new", "name": "New One", "root": "../.."}, "objects": [], "links": []}
    assert L.read_model(c, "new")["objects"] == [] and L.read_model(c, "new")["name"] == "New One"
    E.apply(c, "new", {"op": "add_object", "name": "Shop", "kind": "system"})
    assert [o["id"] for o in L.read_model(c, "new")["objects"]] == ["shop"]
    with pytest.raises(ValueError): E.apply(c, "new", {"op": "create_map"})  # already has one: not an edit op
    with pytest.raises(KeyError): E.apply(c, "ghost", {"op": "create_map"})


def test_check_route_and_edit_route_return_positions(env):
    c, d, p = env; c.close()
    s = server.make_server(p, None, 0); threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    try:
        def get(path):
            try:
                with urllib.request.urlopen(base + path) as r: return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e: return e.code, None
        st, f = get("/api/c4/check?project=p")
        assert st == 200 and set(f) == {"errors", "warnings"} and all({"subject", "message"} <= set(x) for x in f["errors"] + f["warnings"])
        assert get("/api/c4/check?project=new")[0] == 404 and get("/api/c4?project=new")[0] == 404
        tok = get("/api/session")[1]["token"]; oid = get("/api/c4?project=p")[1]["objects"][0]["id"]
        def post(project, op):
            rq = urllib.request.Request(f"{base}/api/c4/edit?project={project}", json.dumps(op).encode(), {"X-Strata-Edit": "1", "Content-Type": "application/json", "X-Strata-Token": tok})
            with urllib.request.urlopen(rq) as r: return json.loads(r.read())
        assert post("p", {"op": "set_positions", "view": "_root", "positions": {oid: [7, 9]}})["model"]["positions"] == {"_root": {oid: [7, 9]}}
        assert get("/api/c4?project=p")[1]["positions"] == {"_root": {oid: [7, 9]}}
        assert post("new", {"op": "create_map"})["model"]["objects"] == [] and get("/api/c4?project=new")[0] == 200
    finally: s.shutdown(); s.server_close()
