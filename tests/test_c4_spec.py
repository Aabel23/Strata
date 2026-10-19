import json, sqlite3, threading, urllib.request
import pytest, yaml
from strata import c4, db, server
from tests.test_c4 import EX, run

OLD = """CREATE TABLE c4_object(id TEXT NOT NULL, project TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('actor','system','app','store','component','group')),
  name TEXT NOT NULL, parent TEXT, technology TEXT, description TEXT, tags JSON, links JSON, status TEXT, PRIMARY KEY(project,id));
CREATE TABLE c4_connection(id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
  name TEXT, technology TEXT, status TEXT, direction TEXT, tags TEXT, PRIMARY KEY(project,id));
INSERT INTO c4_object(id,project,type,name) VALUES('a','p','app','A');"""


def cols(c, t): return {r[1] for r in c.execute(f"PRAGMA table_info({t})")}


def test_migrate_old_db(tmp_path):
    p = tmp_path / "old.db"
    s = sqlite3.connect(p); s.executescript(OLD); s.close()
    c = db.init(p)
    assert {"description", "feature", "interface", "payload", "kind"} <= cols(c, "c4_connection")
    assert {"responsibilities", "state"} <= cols(c, "c4_object")
    assert {"object_id", "signature", "errors"} <= cols(c, "c4_interface")
    assert c.execute("SELECT name FROM c4_object WHERE id='a'").fetchone()[0] == "A"
    c.execute("INSERT INTO c4_object(id,project,type,name) VALUES('f','p','file','f.py')"); c.commit()
    db.init(p)  # idempotent
    assert c.execute("SELECT count(*) FROM c4_object").fetchone()[0] == 2


def test_import_spec_fields(tmp_path):
    p = tmp_path / "t.db"
    assert run(p, "import-yaml", str(EX), "--project", "p")[0] == 0
    m = c4.read_model(db.connect(p), "p")
    o = {x["id"]: x for x in m["objects"]}
    assert o["transport"]["state"] == "stateless" and o["transport"]["responsibilities"]
    assert [i["id"] for i in o["security"]["interfaces"]] == ["sec_open", "sec_close"]
    i = o["security"]["interfaces"][0]
    assert i["object"] == "security" and i["kind"] == "function" and "OpenedRequest" in i["signature"] and isinstance(i["errors"], list)
    assert o["mail"]["interfaces"] == []
    assert o["t_http"]["type"] == "file" and o["s_open"]["parent"] == "s_cloud"
    x = {x["id"]: x for x in m["connections"]}["app_req"]
    assert x["kind"] == "network" and x["interface"] == "transport_post" and set(x["payload"]) == {"request", "response"} and x["feature"]
    # re-import with interfaces removed deletes them
    y = yaml.safe_load(EX.read_text()); y.pop("interfaces")
    for c in y["connections"]: c.pop("interface", None)
    f = tmp_path / "m.yaml"; f.write_text(yaml.safe_dump(y, allow_unicode=True))
    assert run(p, "import-yaml", str(f), "--project", "p")[0] == 0
    assert db.connect(p).execute("SELECT count(*) FROM c4_interface").fetchone()[0] == 0


def base():
    return {"objects": [{"id": "app", "type": "app", "parent": "s"}, {"id": "s", "type": "system"},
                        {"id": "a", "type": "component", "parent": "app"}, {"id": "b", "type": "component", "parent": "app"}],
            "interfaces": [{"id": "ib", "object": "b", "kind": "function"}],
            "connections": [{"id": "x", "from": "a", "to": "b", "interface": "ib", "kind": "call"}]}


@pytest.mark.parametrize("edit,msg", [
    (lambda m: m["interfaces"][0].update(object="nope"), "object 'nope'"),
    (lambda m: m["connections"][0].update(interface="nope"), "interface 'nope' không tồn tại"),
    (lambda m: m["connections"][0].update(to="a"), "không thuộc"),
    (lambda m: m["objects"].append({"id": "f", "type": "file", "parent": "app"}), "file không được nằm trong app"),
    (lambda m: m["objects"].append({"id": "g", "type": "function", "parent": "s"}), "function không được nằm trong system"),
    (lambda m: m["connections"][0].update(kind="rpc"), "kind 'rpc'"),
])
def test_spec_validation(tmp_path, edit, msg):
    m = base()
    assert c4.check(m, tmp_path)[0] == []
    m["objects"] += [{"id": "f1", "type": "file", "parent": "a"}, {"id": "fn", "type": "function", "parent": "f1"}]
    assert c4.check(m, tmp_path)[0] == []
    edit(m)
    assert any(msg in e for e in c4.check(m, tmp_path)[0])
