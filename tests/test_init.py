import pytest
from strata import db, service
from conftest import run


def snap_ok(c, dbp, pid, reindex=False): return "p.json", {"nodes": [1, 2], "relationships": []}


def boom(c, dbp, pid, reindex=False): raise RuntimeError("gitnexus not found")


@pytest.fixture
def c(dbp): return db.init(str(dbp))


@pytest.fixture
def code(tmp_path):
    r = tmp_path / "My App"; (r / "src").mkdir(parents=True); (r / "src/a.py").write_text("x=1\n"); return r


def st(res): return {r["step"]: r["status"] for r in res}


def test_fresh_and_idempotent(c, dbp, code):
    r = service.setup_project(c, str(dbp), code, snapshot=snap_ok)
    assert st(r) == {"project": "done", "docs": "done", "c4": "done", "codemap": "done"}
    assert db.get_project(c, "my-app")["docs_dir"] == str(code / "docs") and (code / "docs/review").is_dir()
    assert c.execute("SELECT count(*) FROM c4_object WHERE project='my-app'").fetchone()[0] == 1
    assert run(dbp, "c4", "validate", str(code / "docs/c4"))[0] == 0
    r = service.setup_project(c, str(dbp), code, snapshot=snap_ok)
    assert [x["status"] for x in r] == ["skipped", "skipped", "skipped", "done"]  # codemap rebuilds each run


def test_empty_folder(c, dbp, tmp_path):
    r = service.setup_project(c, str(dbp), tmp_path, id="e", snapshot=boom)
    assert st(r)["codemap"] == "skipped" and r[-1]["detail"] == "no code found"


def test_no_codemap(c, dbp, code): assert st(service.setup_project(c, str(dbp), code, codemap=False, snapshot=boom))["codemap"] == "skipped"


def test_snapshot_failure(c, dbp, code):
    r = service.setup_project(c, str(dbp), code, snapshot=boom)
    assert r[-1]["status"] == "failed" and "install GitNexus" in r[-1]["detail"]


def test_slug_and_bad_id(c, dbp, tmp_path):
    a = tmp_path / "Foo  Bar!!"; a.mkdir(); assert service.setup_project(c, str(dbp), a, codemap=False)[0]["detail"] == "registered foo-bar"
    b = tmp_path / "!!!"; b.mkdir()
    with pytest.raises(ValueError, match="--id"): service.setup_project(c, str(dbp), b)


def test_id_other_root(c, dbp, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    service.setup_project(c, str(dbp), a, id="x", codemap=False)
    with pytest.raises(ValueError, match="different root"): service.setup_project(c, str(dbp), b, id="x")


def test_cli(dbp, code, tmp_path):
    rc, out = run(dbp, "init", str(code), "--no-codemap")
    assert rc == 0 and "created research, architect, plan, review" in out and out.strip().endswith("#/p/my-app")
    rc, out = run(dbp, "init", str(tmp_path / "x"), "--db-only"); assert rc == 0 and out.startswith("ok:") and out.count("\n") == 1
    d = tmp_path / "e"; d.mkdir(); run(dbp, "init", str(d), "--id", "e", "--no-codemap")
    assert run(dbp, "init", str(code), "--id", "e", "--name", "n")[0] == 0  # same root reused
    f = tmp_path / "f"; f.mkdir(); assert run(dbp, "init", str(f), "--id", "e")[0] == 1
