import os, pathlib, subprocess, sys
import pytest, yaml
from strata import c4, db

ROOT = pathlib.Path(__file__).resolve().parent.parent
EX = ROOT / "examples/project1_app.strata.yaml"


def run(dbp, *args):
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), *args], capture_output=True, text=True,
                       env={**os.environ, "STRATA_DB": str(dbp)})
    return r.returncode, r.stdout


@pytest.fixture
def dbp(tmp_path): return tmp_path / "t.db"


def counts(dbp, project="p"):
    c = db.connect(dbp)
    return tuple(c.execute(f"SELECT count(*) FROM c4_{t} WHERE project=?", (project,)).fetchone()[0] for t in ("object", "connection", "flow"))


def test_import_twice_matches_yaml(dbp):
    m = yaml.safe_load(EX.read_text())
    want = (len(m["objects"]), len(m["connections"]), len(m["flows"]))
    assert run(dbp, "import-yaml", str(EX), "--project", "p")[0] == 0
    assert run(dbp, "import-yaml", str(EX), "--project", "p")[0] == 0
    assert counts(dbp) == want
    c = db.connect(dbp)
    assert c.execute("SELECT count(*) FROM audit WHERE tool='import-yaml'").fetchone()[0] == 2
    root = c.execute("SELECT root FROM c4_meta WHERE project='p'").fetchone()[0]
    assert pathlib.Path(root).is_absolute()


def test_reimport_reflects_changes(dbp, tmp_path):
    m = yaml.safe_load(EX.read_text())
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(m, allow_unicode=True))
    run(dbp, "import-yaml", str(f), "--project", "p", "--force")
    m["objects"] = [o for o in m["objects"] if o["id"] != "gmail"]
    m["connections"] = [c for c in m["connections"] if c["to"] != "gmail"]
    m["flows"] = m["flows"][:1]
    m["objects"][0]["name"] = "Đổi tên"
    f.write_text(yaml.safe_dump(m, allow_unicode=True))
    run(dbp, "import-yaml", str(f), "--project", "p", "--force")
    assert counts(dbp) == (len(m["objects"]), len(m["connections"]), 1)
    assert db.connect(dbp).execute("SELECT name FROM c4_object WHERE id=?", (m["objects"][0]["id"],)).fetchone()[0] == "Đổi tên"
    assert counts(dbp, "other") == (0, 0, 0)


def test_validate_db_matches_yaml(dbp):
    run(dbp, "import-yaml", str(EX), "--project", "p")
    assert run(dbp, "validate", "--project", "p") == run(dbp, "validate", str(EX))


@pytest.mark.parametrize("edit", [
    lambda m: m["objects"][4].update(parent="nope"),
    lambda m: m["flows"][0]["steps"][0].update(connection="nope"),
    lambda m: m["connections"][0].update(to="nope"),
])
def test_bad_model_exit_1(dbp, tmp_path, edit):
    m = yaml.safe_load(EX.read_text())
    edit(m)
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(m, allow_unicode=True))
    assert run(dbp, "import-yaml", str(f), "--project", "p", "--force")[0] == 0
    code, out = run(dbp, "validate", "--project", "p")
    assert code == 1 and "ERROR" in out
    assert run(dbp, "validate", str(f))[0] == 1


def test_validate_unknown_project(dbp):
    assert run(dbp, "validate", "--project", "zz")[0] == 1


def test_malformed_yaml_clean_error(dbp, tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("objects:\n  - just a string\n")
    code, out = run(dbp, "import-yaml", str(f), "--project", "p", "--force")
    assert code == 1 and "ERROR" in out


def test_issues_by_object(tmp_path):
    (tmp_path / "ok.py").write_text("x")
    m = {"objects": [{"id": "a", "links": ["ok.py"], "description": "d"},
                     {"id": "b", "links": ["ok.py", "gone.py"], "description": "d"},
                     {"id": "c", "links": ["http://x"]},
                     {"name": "n", "id": "d", "type": "component", "description": "d"},
                     {"name": "n", "id": "e", "type": "actor", "description": "d"}]}
    assert c4.issues_by_object(m, tmp_path) == {"b": ["dead_link"], "c": ["no_desc"], "d": ["no_link"]}


# ---- task #41: broken YAML must not reach the DB or hang ----
def M(**kw):
    o = lambda i, **k: {"id": i, "type": "system", "name": i.upper(), "description": "d", **k}
    return {"objects": [o("a"), o("b")], "connections": [{"id": "ab", "from": "a", "to": "b", "technology": "t"}], **kw}


def test_parent_cycle_and_dangling(dbp):
    m = M(); m["objects"][0]["parent"] = "b"; m["objects"][1]["parent"] = "a"
    assert any("vòng" in e for e in c4.check(m, ROOT)[0])
    m["objects"][0]["parent"] = "zz"; m["objects"][1].pop("parent")
    assert any("zz" in e for e in c4.check(m, ROOT)[0])
    # context + _lift must terminate on a cycle already in the DB
    c = db.init(dbp)
    c4.import_yaml(c, _write(dbp.parent / "ok.yaml", M()), "p")
    c.execute("UPDATE c4_object SET parent='b' WHERE id='a' AND project='p'")
    c.execute("UPDATE c4_object SET parent='a' WHERE id='b' AND project='p'"); c.commit()
    import concurrent.futures as cf
    ex = cf.ThreadPoolExecutor(1)  # a hang must fail, not block pytest
    try: assert "# a" in ex.submit(lambda: c4.context_text(db.init(dbp), "p", "a")).result(timeout=5)
    finally: ex.shutdown(wait=False)


def test_parent_not_string():
    m = M(); m["objects"][0]["parent"] = ["x"]; m["objects"][1]["parent"] = {"k": 1}
    assert sum("parent phải là chuỗi" in e for e in c4.check(m, ROOT)[0]) == 2


def _write(p, m):
    p.write_text(yaml.safe_dump(m, allow_unicode=True)); return p


def test_null_sections_no_crash():
    m = {"objects": None, "tags": None, "connections": None, "interfaces": None, "flows": None}
    assert c4.check(m, ROOT)[0] == []
    m = M(); m["objects"][0].update(tags=None, links=None); m["flows"] = [{"id": "f", "steps": None}]
    assert c4.check(m, ROOT)[0] == []


def test_name_and_duplicate_ids():
    m = M(); m["objects"][0].pop("name")
    assert any("thiếu name" in e for e in c4.check(m, ROOT)[0])
    m = M(); m["connections"] *= 2
    assert any("trùng id connection" in e for e in c4.check(m, ROOT)[0])
    m = M(flows=[{"id": "f", "steps": [{"id": "s", "at": "a"}, {"id": "s", "at": "a"}]}, {"id": "f", "steps": []}])
    errs = c4.check(m, ROOT)[0]
    assert any("step" in e for e in errs) and any("trùng id flow" in e for e in errs)


def test_import_blocked_on_errors(dbp, tmp_path):
    m = M(); m["objects"][0]["status"] = "zz"
    f = _write(tmp_path / "bad.yaml", m)
    code, out = run(dbp, "import-yaml", str(f), "--project", "p")
    assert code == 1 and counts(dbp) == (0, 0, 0)
    assert run(dbp, "import-yaml", str(f), "--project", "p", "--force")[0] == 0 and counts(dbp)[0] == 2
