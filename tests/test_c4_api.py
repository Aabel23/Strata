import json
import pathlib
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from strata import c4, db, server


@pytest.fixture
def api(tmp_path):
    database = tmp_path / "c4.db"
    source = tmp_path / "map.yaml"
    model = {
        "name": "API test", "root": ".",
        "objects": [
            {"id": "sys", "type": "system", "name": "System"},
            {"id": "app", "type": "app", "name": "App", "parent": "sys",
             "ports": [{"id": "in", "name": "input", "direction": "input"}]},
            {"id": "worker", "type": "component", "name": "Worker", "parent": "app",
             "ports": [{"id": "out", "name": "output", "direction": "output"}]},
        ],
        "connections": [{"id": "existing", "from": "worker", "to": "app", "name": "existing", "from_port": "out", "to_port": "in"}],
        "flows": [], "interfaces": [],
    }
    source.write_text(yaml.safe_dump(model, sort_keys=False), encoding="utf-8")
    conn = db.init(database)
    conn.execute("INSERT INTO project(id,name) VALUES('p','P')")
    c4.import_yaml(conn, source, "p")
    conn.close()
    http = server.make_server(database, "p", 0)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{http.server_address[1]}"
    yield base, database, source
    http.shutdown(); http.server_close(); thread.join()


def request(base, path, body=None, headers=None):
    data = (body if isinstance(body, bytes) else json.dumps(body).encode()) if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", "Origin": base, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read()) if r.headers.get_content_type() == "application/json" else r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()


def post(api, resource, body): return request(api[0], f"/api/c4/{resource}", {"project": "p", **body})


def test_objects_are_transactional_db_mutations_with_audit_and_yaml_untouched(api):
    base, path, source = api
    original = source.read_bytes()
    assert post(api, "object", {"op": "create", "object": {"id": "new", "type": "group", "name": "New", "parent": "sys"}})[0] == 200
    updated = post(api, "object", {"op": "update", "id": "new", "fields": {"name": "Updated"}})
    assert updated[0] == 200 and updated[1]["object"]["name"] == "Updated"
    assert post(api, "object", {"op": "move", "id": "new", "parent": None})[0] == 200
    updated = post(api, "object", {"id": "app", "fields": {"name": "Renamed", "description": "DB text"}})
    assert updated[0] == 200 and updated[1]["object"]["name"] == "Renamed"
    assert post(api, "object", {"id": "app", "fields": {"technology": ""}})[0] == 200
    assert post(api, "object", {"id": "app", "fields": {"status": "future"}})[0] == 200
    assert post(api, "object", {"id": "app", "fields": {"status": ""}})[0] == 200
    assert next(o for o in request(base, "/api/c4?project=p")[1]["objects"] if o["id"] == "app")["name"] == "Renamed"
    c = db.connect(path)
    assert c.execute("SELECT parent FROM c4_object WHERE project='p' AND id='new'").fetchone()[0] is None
    assert {r[0] for r in c.execute("SELECT tool FROM audit WHERE project='p'")} >= {"c4.object.create", "c4.object.move", "c4.object.update"}
    audit = c.execute("SELECT before,after FROM audit WHERE project='p' AND tool='c4.object.update' AND target='c4_object:app' ORDER BY id LIMIT 1").fetchone()
    assert json.loads(audit["before"]) == {"name": "App", "description": None}
    assert json.loads(audit["after"]) == {"name": "Renamed", "description": "DB text"}
    assert source.read_bytes() == original
    assert post(api, "object", {"op": "delete", "id": "new"})[0] == 200
    assert post(api, "object", {"op": "update", "id": "missing", "fields": {"name": "x"}})[0] == 404
    before_failures = c.execute("SELECT count(*) FROM audit WHERE project='p'").fetchone()[0]
    assert post(api, "object", {"id": "app", "fields": {"description": "two\nlines"}})[0] == 400
    assert post(api, "object", {"id": "app", "fields": {"status": "bogus"}})[0] == 400
    assert post(api, "object", {"id": "app", "fields": {"unexpected": "x"}})[0] == 400
    assert post(api, "object", {"id": "app", "fields": {"description": "partial", "status": "bogus"}})[0] == 400
    assert c.execute("SELECT count(*) FROM audit WHERE project='p'").fetchone()[0] == before_failures
    assert next(o for o in request(base, "/api/c4?project=p")[1]["objects"] if o["id"] == "app")["description"] == "DB text"
    assert post(api, "object", {"id": "app", "fields": {"name": "", "description": "partial"}})[0] == 400
    assert next(o for o in request(base, "/api/c4?project=p")[1]["objects"] if o["id"] == "app")["description"] == "DB text"
    assert source.read_bytes() == original


def test_ports_and_links_crud_and_audit(api):
    c = db.connect(api[1])
    assert post(api, "port", {"op": "create", "object": "worker", "port": {"id": "in2", "name": "in2", "direction": "input", "kind": "json"}})[0] == 200
    assert post(api, "port", {"op": "update", "id": "in2", "fields": {"name": "renamed"}})[0] == 200
    created_link = post(api, "link", {"op": "create", "link": {"id": "newlink", "from": "worker", "to": "app", "from_port": "out", "to_port": "in", "name": "new"}})
    assert created_link[0] == 200 and created_link[1]["id"] == "newlink" and created_link[1]["ok"] is True
    assert post(api, "link", {"op": "update", "id": "newlink", "fields": {"name": "updated"}})[0] == 200
    assert post(api, "link", {"op": "delete", "id": "newlink"})[0] == 200
    assert post(api, "port", {"op": "delete", "id": "in2"})[0] == 200
    assert post(api, "link", {"op": "create", "link": {"id": "bad", "from": "app", "to": "worker", "from_port": "out"}})[0] == 400
    assert c.execute("SELECT count(*) FROM c4_connection WHERE project='p' AND id='bad'").fetchone()[0] == 0
    assert {r[0] for r in c.execute("SELECT tool FROM audit WHERE project='p'")} >= {
        "c4.port.create", "c4.port.update", "c4.port.delete", "c4.link.create", "c4.link.update", "c4.link.delete"}


def test_post_guards_remain_and_positions_route_is_gone(api):
    base, dbp, source = api
    original = source.read_bytes()
    assert request(base, "/api/c4/object", {"project": "p", "op": "update", "id": "app", "fields": {"name": "X"}}, {"Origin": "http://evil"})[0] == 403
    assert request(base, "/api/c4/object", {"project": "p", "op": "update", "id": "app", "fields": {"name": "X"}}, {"Host": "evil"})[0] == 403
    assert request(base, "/api/c4/object", {"project": "p", "op": "update", "id": "app", "fields": {"name": "X"}}, {"Content-Type": "text/plain"})[0] == 403
    assert request(base, "/api/c4/object", b"{")[0] == 400
    assert request(base, "/api/c4/object", b" " * 200_001)[0] == 400
    assert request(base, "/api/c4/positions", {"project": "p", "level": "_root", "positions": {"app": [1, 2]}})[0] == 404
    assert source.read_bytes() == original


def test_editor_has_no_drawflow_or_stored_layout():
    root = pathlib.Path(__file__).parents[1]
    page = (root / "viewer" / "index.html").read_text(encoding="utf-8")
    assert not list((root / "viewer" / "vendor").glob("*rawflow*"))
    assert "drawflow" not in page.lower() and "positions" not in page and "savepos" not in page
    assert "https://cdn" not in page and "http://cdn" not in page
    for required in ("async function postC4(path,body)", 'postC4("port"'):
        assert required in page
