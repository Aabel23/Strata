import pathlib, shutil
import pytest, yaml
from strata import c4_layered as L, db
from test_c4 import dbp, run

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
    assert any("RelayHub.removed" in x and "chưa resolve" in x for x in w)
    assert any("push.dart" in x and "chưa resolve" in x for x in w)
    assert len(w) == 2          # flow is continuous, python symbols that exist raise nothing
    assert L.report(folder) == 0
    assert "3/5 link có detail" in capsys.readouterr().out


def test_non_python_existing_file_warns(folder):
    (folder.parent / "lib").mkdir(); (folder.parent / "lib/push.dart").write_text("x")
    m, _ = L.load(folder)
    assert any("không phải Python" in x for x in L.check(m, folder)[1])


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
    assert any(msg in e for e in errs), errs


def test_flow_errors_and_gap(folder):
    p = folder / "flows/send_command.yaml"
    p.write_text(p.read_text().replace("{at: relay, transition: t1}", "{link: nope}").replace("{link: user_app, text: tap}", "{link: relay_db}"))
    m, errs = L.load(folder)
    e, w, _ = L.check(m, folder)
    assert any("link 'nope'" in x for x in e) and any("đứt mạch" in x for x in w)


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


def test_old_import_yaml_still_works(tmp_path):
    from test_c4 import EX
    dbp = tmp_path / "t.db"
    assert run(dbp, "import-yaml", str(EX), "--project", "p")[0] == 0
    assert run(dbp, "validate", "--project", "p")[0] == 0


def test_import_over_old_project_with_bound_ports(folder, tmp_path):
    old = tmp_path / "old.strata.yaml"
    old.write_text(yaml.safe_dump({"name": "Old", "root": ".", "objects": [
        {"id": "s", "type": "system", "name": "S", "description": "x"},
        {"id": "a", "type": "app", "parent": "s", "name": "A", "description": "x", "ports": [{"id": "pa", "name": "pa", "direction": "output"}]},
        {"id": "b", "type": "app", "parent": "s", "name": "B", "description": "x"}],
        "connections": [{"id": "ab", "from": "a", "to": "b", "technology": "t", "from_port": "pa"}]}))
    dbp = tmp_path / "t.db"
    assert run(dbp, "import-yaml", str(old), "--project", "p")[0] == 0
    rc, out = run(dbp, "c4", "import", str(folder), "--project", "p")
    assert rc == 0, out
    c = db.connect(dbp)
    assert c.execute("SELECT count(*) FROM c4_port").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM c4_connection WHERE from_port_id IS NOT NULL").fetchone()[0] == 0
    import json
    assert json.loads(c.execute("SELECT before FROM audit WHERE tool='c4-import'").fetchone()[0])["port"] == 1


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


def test_old_format_unchanged(dbp, tmp_path):
    from test_c4 import EX
    run(dbp, "project", "add", "p", "--name", "P"); run(dbp, "import-yaml", str(EX), "--project", "p")
    c = db.connect(dbp)
    assert not L.is_layered(c, "p")
    from strata import c4
    assert c4.flow_text(c, "p", "menu_refresh").splitlines()[7].startswith("7. cloud.CloudClient.post/_send → transport.http.Handler.do_POST [network]")
    assert c4.context_text(c, "p").startswith("# ") and "Connection:" in c4.context_text(c, "p")
