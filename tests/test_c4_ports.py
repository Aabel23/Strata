import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest
import yaml

from strata import c4, db, service

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def dbp(tmp_path):
    return tmp_path / "t.db"


def run(dbp, *args):
    return subprocess.run([sys.executable, str(ROOT / "strata.py"), *args], capture_output=True, text=True,
                          env={**os.environ, "STRATA_DB": str(dbp)})


def model(**extra):
    return {
        "name": "Port demo", "root": ".",
        "objects": [
            {"id": "sys", "type": "system", "name": "System", "description": "system"},
            {"id": "a", "type": "app", "kind": "service", "parent": "sys", "name": "A", "description": "a",
             "ports": [{"id": "a_in", "name": "input", "direction": "input", "kind": "json", "schema": {"type": "object"}}]},
            {"id": "b", "type": "component", "name": "B", "parent": "a", "description": "b",
             "ports": [{"id": "b_out", "name": "output", "direction": "output", "kind": "json"}]},
        ],
        "connections": [{"id": "ab", "from": "b", "to": "a", "from_port": "b_out", "to_port": "a_in", "name": "send"}],
        "interfaces": [], "flows": [{"id": "f", "name": "Flow", "steps": [{"connection": "ab"}]}],
        **extra,
    }


def test_migration_preserves_existing_c4_rows(tmp_path):
    dbp = tmp_path / "old.db"
    old = sqlite3.connect(dbp)
    old.executescript("""
        CREATE TABLE c4_object(id TEXT NOT NULL, project TEXT NOT NULL,
          type TEXT NOT NULL CHECK(type IN ('actor','system','app','store','component','group','file','function')),
          name TEXT NOT NULL, parent TEXT, technology TEXT, description TEXT, tags JSON, links JSON,
          status TEXT, responsibilities JSON, state TEXT, PRIMARY KEY(project,id));
        CREATE TABLE c4_connection(id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
          name TEXT, technology TEXT, status TEXT, direction TEXT, tags TEXT, PRIMARY KEY(project,id));
        CREATE TABLE c4_meta(project TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT, layout TEXT, tags JSON);
        INSERT INTO c4_object(id,project,type,name) VALUES('a','p','app','A');
        INSERT INTO c4_connection(id,project,from_id,to_id,name) VALUES('ab','p','a','a','loop');
        INSERT INTO c4_meta(project,name,root,layout) VALUES('p','P','.','lr');
        CREATE TABLE object_layout(project TEXT, level TEXT, object_id TEXT, x REAL, y REAL);
        INSERT INTO object_layout VALUES('p','_root','a',1,2);
    """)
    old.commit(); old.close()
    c = db.init(dbp)
    assert c.execute("SELECT name FROM c4_object WHERE project='p' AND id='a'").fetchone()[0] == "A"
    assert c.execute("SELECT name FROM c4_connection WHERE project='p' AND id='ab'").fetchone()[0] == "loop"
    assert "kind" in {r[1] for r in c.execute("PRAGMA table_info(c4_object)")}
    assert {"from_port_id", "to_port_id"} <= {r[1] for r in c.execute("PRAGMA table_info(c4_connection)")}
    assert c.execute("SELECT count(*) FROM c4_port").fetchone()[0] == 0
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='object_layout'").fetchone()


def test_import_export_round_trip(dbp, tmp_path):
    source = tmp_path / "model.yaml"
    source.write_text(yaml.safe_dump(model(), allow_unicode=True))
    c = db.init(dbp)
    c4.import_yaml(c, source, "p")
    assert c4.export_model(c, "p") == model()


@pytest.mark.parametrize("direction", ["sideways", "", None])
def test_invalid_port_direction_rejected(dbp, tmp_path, direction):
    m = model(); m["objects"][1]["ports"][0]["direction"] = direction
    f = tmp_path / "bad.yaml"; f.write_text(yaml.safe_dump(m))
    with pytest.raises(ValueError, match="direction"):
        c4.import_yaml(db.init(dbp), f, "p")


def test_port_ids_project_unique_and_port_owner_required(dbp, tmp_path):
    c = db.init(dbp)
    m = model()
    m["objects"][2]["ports"] = [{"id": "a_in", "name": "x", "direction": "input"}]
    with pytest.raises(ValueError, match="port|trùng|duplicate"):
        c4.import_yaml(c, _write(tmp_path / "bad.yaml", m), "p")


def test_unknown_nested_port_fields_are_reported():
    m = model()
    m["objects"][2]["ports"][0]["schemae"] = {"type": "string"}
    warns = c4.check(m, ROOT)[1]
    assert any("port b_out" in w and "schemae" in w for w in warns)


def test_port_connection_must_belong_to_endpoint_and_legacy_positions_are_ignored(dbp, tmp_path):
    m = model(positions={"_root": {"a": [12, 13]}})
    m["connections"][0]["from_port"] = "a_in"
    f = _write(tmp_path / "bad.yaml", m)
    with pytest.raises(ValueError, match="from_port"):
        c4.import_yaml(db.init(dbp), f, "p")
    m["connections"][0]["from_port"] = "b_out"
    c = db.init(dbp); c4.import_yaml(c, _write(f, m), "p")
    assert "positions" not in c4.export_model(c, "p")


def _write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    return path


def test_service_and_cli_ports_kind_are_audited(dbp, tmp_path):
    c = db.init(dbp)
    c.execute("INSERT INTO project(id,name) VALUES('p','P')")
    c4.import_yaml(c, _write(tmp_path / "model.yaml", model()), "p")
    service.add_c4_port(c, "main", "p", "a", "cli_in", "in", "input", "json", {"type": "object"})
    service.set_c4_kind(c, "main", "p", "a", "worker")
    assert service.list_c4_ports(c, "p", "a")[-1]["id"] == "cli_in"
    assert c.execute("SELECT count(*) FROM audit WHERE tool LIKE 'c4.%'").fetchone()[0] == 2
    c.close()
    for args in (
        ("c4", "port", "add", "--project", "p", "--object", "a", "--id", "cli2", "--name", "second", "--direction", "input", "--kind", "json"),
        ("c4", "port", "list", "--project", "p", "--object", "a"),
        ("c4", "kind", "set", "--project", "p", "--object", "a", "--kind", "worker2"),
    ):
        assert run(dbp, *args).returncode == 0
