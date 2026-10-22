import json
import pathlib, shutil
import pytest, yaml
from strata import c4_layered as L, db
from conftest import FIX, run

FIX = pathlib.Path(__file__).parent / "fixtures/c4_layered"


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "c4"; shutil.copytree(FIX, d)
    (tmp_path / "src").mkdir()
    (d / "../src/app.py").write_text("class App:\n    def ask(self): pass\ndef helper(): pass\n")
    (d / "../src/relay.py").write_text("class RelayHub:\n    def send(self): pass\n    def push(self): pass\n")
    (d / "map.yaml").write_text((d / "map.yaml").read_text().replace("root: .", "root: .."))
    return d


def test_validate_fixture(folder, capsys):
    m, errs = L.load(folder)
    e, w, st = L.check(m, folder)
    assert errs == [] and e == []
    assert st == {"object": 5, "link": 5, "contract": 3, "behavior": 1, "flow": 1, "detail": 3}
    assert any("RelayHub.removed" in x and "chưa resolve" in x for x in map(L.fmt, w))
    assert any("push.dart" in x and "chưa resolve" in x for x in map(L.fmt, w))
    assert len(w) == 2          # flow is continuous, python symbols that exist raise nothing
    assert L.report(folder) == 0
    assert "3/5 link có detail" in capsys.readouterr().out


def test_non_python_existing_file_warns(folder):
    (folder.parent / "lib").mkdir(); (folder.parent / "lib/push.dart").write_text("x")
    m, _ = L.load(folder)
    assert any("không phải Python" in x for x in map(L.fmt, L.check(m, folder)[1]))


@pytest.mark.parametrize("edit,msg", [
    (("detail: relay_command.send", "detail: relay_command.nope"), "detail 'relay_command.nope'"),
    (("parent: cloud, name: Relay", "parent: zz, name: Relay"), "parent 'zz'"),
    (("behavior: relay", "behavior: nope"), "behavior 'nope'"),
    (("from: relay, to: db", "from: relay, to: zz"), "to 'zz'"),
    (("summary: Forwards commands,", "summary: Forwards commands, files: x,"), "key lạ"),
    (("kind: store", "kind: file"), "kind 'file'"),
])
def test_map_errors(folder, edit, msg):
    p = folder / "map.yaml"; p.write_text(p.read_text().replace(*edit))
    m, errs = L.load(folder)
    errs += L.check(m, folder)[0]
    assert any(msg in L.fmt(e) for e in errs), errs


def test_flow_errors_and_gap(folder):
    p = folder / "flows/send_command.yaml"
    p.write_text(p.read_text().replace("{at: relay, transition: t1}", "{link: nope}").replace("{link: user_app, text: tap}", "{link: relay_db}"))
    m, errs = L.load(folder)
    e, w, _ = L.check(m, folder)
    assert any("link 'nope'" in x for x in map(L.fmt, e)) and any("đứt mạch" in x for x in map(L.fmt, w))


def test_import_export_roundtrip(folder, tmp_path):
    dbp = tmp_path / "t.db"
    assert run(dbp, "c4", "validate", str(folder))[0] == 0
    rc, out = run(dbp, "c4", "import", str(folder), "--project", "p")
    assert rc == 0 and "5 object, 5 connection, 1 flow, 3 contract, 1 behavior" in out
    assert run(dbp, "c4", "import", str(folder), "--project", "p")[0] == 0     # idempotent upsert
    c = db.connect(dbp)
    assert c.execute("SELECT count(*) FROM audit WHERE tool='c4-import'").fetchone()[0] == 2
    assert c.execute("SELECT detail FROM c4_connection WHERE id='app_cmd'").fetchone()[0] == "relay_command.send"
    out2 = tmp_path / "out"
    assert run(dbp, "c4", "export", str(out2), "--project", "p")[0] == 0
    a, b = L.load(folder)[0], L.load(out2)[0]
    assert b["behavior"]["relay"]["transitions"][0]["on"] == "send"  # `on:` is not the YAML 1.1 boolean
    a["project"], b["project"] = {}, {}
    assert a == b
    assert (out2 / "flows/send_command.yaml").is_file() and (out2 / "behavior/relay.yaml").is_file()
    assert yaml.safe_load((out2 / "contracts/relay_command.yaml").read_text()) == yaml.safe_load((folder / "contracts/relay_command.yaml").read_text())


def test_import_rejects_errors_and_drops_removed(folder, tmp_path):
    dbp = tmp_path / "t.db"
    assert run(dbp, "c4", "import", str(folder), "--project", "p")[0] == 0
    (folder / "flows/send_command.yaml").unlink()
    assert run(dbp, "c4", "import", str(folder), "--project", "p")[0] == 0
    assert db.connect(dbp).execute("SELECT count(*) FROM c4_flow").fetchone()[0] == 0
    p = folder / "map.yaml"; p.write_text(p.read_text().replace("to: db", "to: zz"))
    assert run(dbp, "c4", "import", str(folder), "--project", "p")[0] == 1
    assert db.connect(dbp).execute("SELECT count(*) FROM c4_object").fetchone()[0] == 5


@pytest.fixture
def lay(folder, dbp):
    assert run(dbp, "project", "add", "demo", "--name", "Demo")[0] == 0 and run(dbp, "c4", "import", str(folder), "--project", "demo")[0] == 0
    return dbp


def test_flow_text_layered(lay):
    code, out = run(lay, "c4", "flow", "--project", "demo", "--id", "send_command")
    ln = out.splitlines()
    assert code == 0 and ln[1] == "1. User → App [Uses] tap"
    assert ln[2] == "2. App → Relay [Send command] | command=start"
    assert ln[3] == "   ↳ src/app.py::App.ask, src/app.py::helper → src/relay.py::RelayHub.send"
    assert ln[4] == "3. @ Relay (transition t1)"
    assert ln[5].startswith("4. Relay → App [Send command ↩] result") and ln[6].startswith("   ↳ src/relay.py::RelayHub.send → ")
    assert "send_command  4 bước" in run(lay, "c4", "flow", "--project", "demo")[1]
    assert run(lay, "c4", "flow", "--project", "demo", "--id", "zz")[0] == 1


def test_context_and_contract_layered(lay):
    out = run(lay, "c4", "context", "--project", "demo")[1]
    assert "  - relay [component] Relay" in out and "- app_cmd: app→relay Send command +detail" in out and "- relay_db: relay→db Save state\n" in out
    out = run(lay, "c4", "context", "--project", "demo", "--object", "relay")[1]
    assert "Behavior relay: machine, 2 state, 1 transition" in out and "    HTTPS POST /command/send" in out and "- send_command:" in out
    assert run(lay, "c4", "context", "--project", "demo", "--object", "zz")[0] == 1
    code, out = run(lay, "c4", "contract", "relay_command.send", "--project", "demo")
    assert code == 0 and "HTTPS POST /command/send" in out and "errors: [\"BUSY\", \"TIMEOUT\"]" in out and "→ src/relay.py::RelayHub.send" in out
    assert run(lay, "c4", "contract", "nope", "--project", "demo")[0] == 1


def test_step_ends():
    objs = {"a": {}, "b": {}, "b1": {"parent": "b"}}
    conns = {"ab": {"from": "a", "to": "b"}}
    assert L.step_ends({"connection": "ab"}, conns, objs) == (("a", "b"), None)
    assert L.step_ends({"connection": "ab", "reverse": True}, conns, objs) == (("b", "a"), None)
    assert L.step_ends({"at": "b"}, conns, objs) == (("b", "b"), None)
    for step in ({}, {"connection": "ab", "at": "a"}, {"at": "zz"}, {"connection": "zz"}, {"at": "a", "reverse": True}, {"from": "a", "to": "b"}):
        assert L.step_ends(step, conns, objs)[1]
    assert L._related(objs, "b", "b1") and not L._related(objs, "a", "b1")


def test_import_drops_orphan_links_and_unlink_works_for_missing_object(lay):
    assert run(lay, "item", "add", "--project", "demo", "--kind", "issue", "--title", "T")[0] == 0
    assert run(lay, "c4", "link", "--project", "demo", "--object", "relay", "--item", "1")[0] == 0
    c = db.connect(lay)
    c.execute("INSERT INTO c4_link VALUES('demo','ghost','item',1)"); c.commit()   # what an older import left behind
    assert run(lay, "c4", "unlink", "--project", "demo", "--object", "ghost", "--item", "1") == (0, "ok\n")
    c.execute("INSERT INTO c4_link VALUES('demo','ghost','item',1)"); c.commit()
    assert run(lay, "c4", "import", str(FIX), "--project", "demo")[0] == 1   # refused: would drop ghost link
    assert run(lay, "c4", "import", str(FIX), "--project", "demo", "--yes")[0] == 0
    assert c.execute("SELECT object_id FROM c4_link").fetchall()[0][0] == "relay" and c.execute("SELECT count(*) FROM c4_link").fetchone()[0] == 1


OLD = """
CREATE TABLE c4_object(id TEXT NOT NULL, project TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('actor','system','app','store','component','group','file','function')),
  name TEXT NOT NULL, parent TEXT, technology TEXT, description TEXT, PRIMARY KEY(project,id));
CREATE TABLE c4_port(project TEXT NOT NULL, id TEXT NOT NULL, object_id TEXT NOT NULL, name TEXT, direction TEXT, kind TEXT, schema_json JSON, PRIMARY KEY(project,id));
CREATE TABLE c4_connection(id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, name TEXT, status TEXT, from_port_id TEXT, to_port_id TEXT,
  PRIMARY KEY(project,id), FOREIGN KEY(project,from_port_id) REFERENCES c4_port(project,id));
CREATE TABLE c4_interface(project TEXT NOT NULL, id TEXT NOT NULL, object_id TEXT NOT NULL, PRIMARY KEY(project,id));
CREATE TABLE c4_meta(project TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT, layout TEXT, tags JSON, positions JSON, source TEXT);
CREATE TABLE c4_link(project TEXT NOT NULL, object_id TEXT NOT NULL, ref_kind TEXT NOT NULL, ref_id INTEGER NOT NULL, PRIMARY KEY(project,object_id,ref_kind,ref_id));
INSERT INTO c4_meta(project,name,source) VALUES('old','Old','/x/old.strata.yaml'),('lay','Lay','/x/docs/c4'),('none','None',NULL);
INSERT INTO c4_object(id,project,type,name) VALUES('a','old','app','A'),('b','old','app','B'),('a','lay','app','A'),('a','none','app','A');
INSERT INTO c4_port VALUES('old','pa','a','pa','output',NULL,NULL);
INSERT INTO c4_connection VALUES('ab','old','a','b','x',NULL,'pa',NULL),('ab','lay','a','a','y',NULL,NULL,NULL);
INSERT INTO c4_interface VALUES('old','i','a');
INSERT INTO c4_link VALUES('old','a','item',1),('lay','a','item',1),('lay','gone','item',2),('none','a','item',3);
"""


def test_migration_drops_old_format_with_backup(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    s = sqlite3.connect(p); s.executescript(OLD); s.close()
    c = db.init(p)
    q = lambda sql: c.execute(sql).fetchall()
    assert [tuple(r) for r in q("SELECT project,id FROM c4_object")] == [("lay", "a")]
    assert [tuple(r) for r in q("SELECT project,id,name FROM c4_connection")] == [("lay", "ab", "y")]
    assert [tuple(r) for r in q("SELECT project FROM c4_meta")] == [("lay",)]
    assert [tuple(r) for r in q("SELECT project,object_id FROM c4_link")] == [("lay", "a")]     # old/none projects and the orphan 'gone' removed
    assert not q("SELECT name FROM sqlite_master WHERE name IN ('c4_port','c4_interface')")
    c.execute("INSERT INTO c4_connection(id,project,from_id,to_id) VALUES('z','lay','a','a')"); c.commit()  # no dangling FK to c4_port
    [b] = list((tmp_path / "backups").glob("strata-pre-old-c4-drop-*.db"))
    k = sqlite3.connect(b)
    assert k.execute("SELECT count(*) FROM c4_port").fetchone()[0] == 1 and k.execute("SELECT count(*) FROM c4_object").fetchone()[0] == 4
    db.init(p)   # idempotent, no second backup
    assert len(list((tmp_path / "backups").glob("strata-pre-old-c4-drop-*.db"))) == 1


def test_dry_run_diff_and_dropped_link_refusal(folder, tmp_path):
    p = tmp_path / "t.db"
    run(p, "project", "add", "p", "--name", "P")
    assert run(p, "c4", "import", str(folder), "--project", "p")[0] == 0
    run(p, "item", "add", "--project", "p", "--kind", "task", "--title", "Làm mail")
    assert run(p, "c4", "link", "--project", "p", "--object", "db", "--item", "1")[0] == 0
    m = yaml.safe_load((folder / "map.yaml").read_text())
    m["objects"] = [o for o in m["objects"] if o["id"] != "db"] + [{"id": "extra", "kind": "app", "name": "X"}]
    m["links"] = [x for x in m["links"] if x["id"] != "relay_db"]
    m["objects"][0]["name"] = "Renamed"
    (folder / "map.yaml").write_text(yaml.safe_dump(m))
    count = lambda: db.connect(p).execute("SELECT count(*) FROM c4_object").fetchone()[0]
    code, out = run(p, "c4", "import", str(folder), "--project", "p", "--dry-run")
    assert code == 0 and count() == 5
    assert "+ extra" in out and "- db" in out and "~ user" in out and "- relay_db" in out and "item #1 Làm mail (object db)" in out
    code, js = run(p, "c4", "diff", str(folder), "--project", "p", "--json")
    d = __import__("json").loads(js)
    assert d["object"] == {"added": ["extra"], "changed": ["user"], "removed": ["db"]} and d["link"]["removed"] == ["relay_db"]
    assert d["dropped_links"][0]["id"] == 1
    code, out = run(p, "c4", "import", str(folder), "--project", "p")          # refused, nothing written
    assert code == 1 and "item #1" in out and count() == 5
    assert run(p, "c4", "import", str(folder), "--project", "p", "--yes")[0] == 0
    assert count() == 5 and run(p, "c4", "diff", str(folder), "--project", "p")[1].count("+0 ~0 -0") == 5
    a = db.connect(p).execute("SELECT after FROM audit WHERE tool='c4-import' ORDER BY id DESC").fetchone()[0]
    assert __import__("json").loads(a)["diff"]["object"]["added"] == ["extra"]


def test_findings_shape_and_report_modes(folder, capsys):
    p = folder / "map.yaml"; p.write_text(p.read_text().replace("kind: store", "kind: file"))
    m, errs = L.load(folder)
    errs += L.check(m, folder)[0]
    assert errs and all(set(f) == {"id", "severity", "subject", "message", "fix"} for f in errs)
    assert "C4-BAD-KIND" in {f["id"] for f in errs}
    capsys.readouterr()
    assert L.report(folder, json_out=True) == 1
    out = json.loads(capsys.readouterr().out)
    assert all(set(f) == {"id", "severity", "subject", "message", "fix"} for f in out)
    assert any(f["id"] == "C4-BAD-KIND" for f in out)


def test_strict_fails_on_warning_only(folder, capsys):
    assert L.report(folder) == 0 and L.report(folder, strict=True) == 1
    assert "WARN  [C4-SYMBOL-UNRESOLVED]" in capsys.readouterr().out
