import json, shutil, threading, urllib.request, urllib.error
import pytest
from strata import c4_layered as L, db, server
from conftest import FIX


@pytest.fixture
def srv(tmp_path):
    d = tmp_path / "c4"; shutil.copytree(FIX, d); (tmp_path / "src").mkdir()
    (d / "map.yaml").write_text((d / "map.yaml").read_text().replace("root: .", "root: .."))
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P", root=str(tmp_path)); L.import_dir(c, d, "p"); c.close()
    made = []
    def start(**kw):
        s = server.make_server(p, None, 0, **kw); made.append(s)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        return s, f"127.0.0.1:{s.server_address[1]}"
    yield start
    for s in made: s.shutdown(); s.server_close()


def tok(hp):
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: return json.load(r)["token"]


def call(hp, method="POST", path="/api/c4/edit?project=p", body=None, **hdr):
    h = {"X-Strata-Edit": "1", "Content-Type": "application/json", "X-Strata-Token": tok(hp)}; h.update(hdr)
    h = {k: v for k, v in h.items() if v is not None}
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request("http://" + hp + path, data, h, method=method)) as r: return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}"), e.headers


ADD = {"op": "add_object", "name": "Cache Unit", "kind": "component", "parent": "cloud"}


def test_success_changes_model(srv):
    _, hp = srv()
    st, r, _ = call(hp, body=ADD)
    assert st == 200 and r["ok"] and "map.yaml" in r["changed"]
    assert any(o["id"] == "cache_unit" for o in r["model"]["objects"])
    with urllib.request.urlopen(f"http://{hp}/api/c4?project=p") as g: assert any(o["id"] == "cache_unit" for o in json.load(g)["objects"])


def test_guards(srv):
    _, hp = srv()
    assert call(hp, body=ADD, **{"X-Strata-Edit": None})[0] == 403
    assert call(hp, body=ADD, Origin="http://evil.com")[0] == 403
    assert call(hp, body=ADD, Origin="http://" + hp.upper())[0] == 200
    assert call(hp, body=ADD, **{"Content-Type": "text/plain"})[0] == 415
    assert call(hp, body=b"x" * 70000)[0] == 413
    assert call(hp, body=b"{nope")[0] == 400 and call(hp, body=[1])[0] == 400
    st, r, _ = call(hp, body={"op": "nope"}); assert st == 400 and "unknown op" in r["error"]
    assert call(hp, path="/api/c4/edit", body=ADD)[0] == 200  # single project -> default_project()


def test_methods_and_paths(srv):
    _, hp = srv()
    assert call(hp, path="/api/items", body=ADD)[0] == 405
    for m in ("PUT", "DELETE", "PATCH"):
        st, _, h = call(hp, method=m, body=ADD); assert st == 405 and h["Allow"] == "POST"
    assert call(hp, "GET", "/api/c4?project=p")[0] == 200


def test_allow_edit_rules(srv):
    _, hp = srv(allow_edit=False); assert call(hp, body=ADD)[0] == 403
    _, hp = srv(); assert call(hp, body=ADD)[0] == 200  # loopback default on
    assert {h for h in server.LOOPBACK} == {"127.0.0.1", "::1", "localhost"}
    _, hp = srv(host="127.0.0.1", allow_edit=True); assert call(hp, body=ADD)[0] == 200
