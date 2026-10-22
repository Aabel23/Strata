import pytest
from strata import db, service


@pytest.fixture
def c(tmp_path):
    c = db.init(str(tmp_path / "t.db")); db.add_project(c, "p", "P"); return c


def roles(c):
    return [(r["tool"], r["actor_role"]) for r in c.execute("SELECT tool,actor_role FROM audit WHERE tool LIKE 'item.%' ORDER BY id")]


def test_main_all(c):
    t = service.add_item(c, "main", "p", "task", "T"); service.add_item(c, "main", "p", "issue", "I")
    service.set_item(c, "main", t, "doing", "high")
    assert c.execute("SELECT created_by FROM item WHERE id=?", (t,)).fetchone()[0] == "main"
    assert roles(c) == [("item.add", "main"), ("item.add", "main"), ("item.transition", "main"), ("item.set", "main")]


def test_coder(c):
    t = service.add_item(c, "main", "p", "task", "T")
    i = service.add_item(c, "coder", "p", "issue", "I")
    service.set_item(c, "coder", t, "doing")
    with pytest.raises(PermissionError): service.add_item(c, "coder", "p", "task", "X")
    with pytest.raises(PermissionError): service.set_item(c, "coder", t, priority="high")
    with pytest.raises(PermissionError): service.set_item(c, "coder", i, "done")  # not a task
    assert roles(c)[1:] == [("item.add", "coder"), ("item.transition", "coder")]


def test_reviewer(c):
    t = service.add_item(c, "main", "p", "task", "T")
    service.add_item(c, "reviewer", "p", "issue", "I")
    with pytest.raises(PermissionError): service.add_item(c, "reviewer", "p", "task", "X")
    with pytest.raises(PermissionError): service.set_item(c, "reviewer", t, "done")
    assert roles(c)[-1] == ("item.add", "reviewer") and len(roles(c)) == 2


def test_unknown_role(c):
    with pytest.raises(PermissionError): service.add_item(c, "root", "p", "issue", "I")


def test_search_rank_filters_fold(c):
    db.add_project(c, "q", "Q")
    b = service.add_item(c, "main", "p", "task", "other", "zebra here")
    t = service.add_item(c, "main", "p", "task", "zebra", "other")
    service.add_item(c, "main", "q", "task", "zebra q")
    service.add_item(c, "main", "p", "task", "Đường đi", "x")
    assert [h["ref"] for h in service.search(c, "zebra", "p")][:2] == [t, b]
    assert {h["project"] for h in service.search(c, "zebra")} == {"p", "q"}
    assert len(service.search(c, "zebra", limit=1)) == 1
    assert service.search(c, "zebra", src="page") == []
    assert len(service.search(c, "zebra", limit=10**6)) == 3
    assert service.search(c, "đường")
    assert service.search(c, 'a" or * (') == []
    with pytest.raises(ValueError): service.search(c, "  ")


def test_cli_search(c, tmp_path, capsys):
    import importlib.util, pathlib
    sp = importlib.util.spec_from_file_location("cli", pathlib.Path(__file__).parent.parent / "strata.py"); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    service.add_item(c, "main", "p", "task", "needle title"); c.close()
    db_ = str(tmp_path / "t.db")
    assert m.main(["search", "needle", "--db", db_, "--project", "p", "--src", "item", "--limit", "5"]) == 0
    assert capsys.readouterr().out.strip().endswith("p needle title")


def test_non_main_status_rules(c):
    t = service.add_item(c, "main", "p", "task", "T")
    for st in ("approved", "open", "rejected"):
        with pytest.raises(PermissionError): service.set_item(c, "coder", t, st)
    service.set_item(c, "coder", t, "doing")
    i = service.add_item(c, "coder", "p", "issue", "I", status="done")
    assert c.execute("SELECT status FROM item WHERE id=?", (i,)).fetchone()[0] == "proposed"
    j = service.add_item(c, "main", "p", "issue", "J", status="done")
    assert c.execute("SELECT status FROM item WHERE id=?", (j,)).fetchone()[0] == "done"


def denied(c): return [dict(r) for r in c.execute("SELECT * FROM audit WHERE tool LIKE 'denied:%' ORDER BY id")]


def test_denials_audited_without_body(c):
    with pytest.raises(PermissionError): service.add_item(c, "coder", "p", "task", "T" * 200, body="SECRET-BODY")
    with pytest.raises(PermissionError): service.add_item(c, "hacker", "p", "issue", "x", body="SECRET-BODY")
    i = service.add_item(c, "main", "p", "task", "t")
    with pytest.raises(PermissionError): service.set_item(c, "reviewer", i, status="done")
    with pytest.raises(PermissionError): service.set_item(c, "coder", 999, priority="p1")
    d = denied(c)
    assert [(r["tool"], r["actor_role"]) for r in d] == [
        ("denied:item.add", "coder"), ("denied:item.add", "invalid"), ("denied:item.transition", "reviewer"),
        ("denied:item.set", "coder")]
    assert d[0]["project"] == "p" and d[2]["project"] == "p" and d[3]["project"] == "-"
    assert "SECRET" not in str(d) and ("T" * 81) not in str(d)


def test_missing_project_keyerror(c):
    for p in ("nope", ""):
        with pytest.raises(KeyError): service.add_item(c, "main", p, "task", "t")
        with pytest.raises(KeyError): db.add_item(c, p, "task", "t")
    assert c.execute("SELECT count(*) FROM audit WHERE tool='item.add'").fetchone()[0] == 0


def test_cli_missing_project_clean(tmp_path):
    import subprocess, sys
    r = subprocess.run([sys.executable, "strata.py", "item", "add", "--project", "zz", "--kind", "task", "--title", "t", "--db", str(tmp_path / "x.db")], capture_output=True, text=True)
    assert r.stdout.strip() == "ERROR no project zz" and "Traceback" not in r.stderr


def test_search_validation(c):
    service.add_item(c, "main", "p", "task", "alpha")
    with pytest.raises(ValueError, match="unknown src"): service.search(c, "alpha", src="foo")
    with pytest.raises(ValueError, match="bad limit"): service.search(c, "alpha", limit="abc")
    assert len(service.search(c, "alpha", limit=1000, src="item", project="p")) == 1
    assert len(service.search(c, "alpha", limit=-5)) == 1


def test_default_db_absolute():
    import pathlib
    assert pathlib.Path(db.DEFAULT_DB).is_absolute() and db.DEFAULT_DB.endswith("strata.db")
