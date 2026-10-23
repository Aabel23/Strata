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


def test_issue_is_labelled_task(c):
    for role in ("reviewer", "coder"):
        i = service.add_item(c, role, "p", "task", "I", label="issue")
        assert tuple(c.execute("SELECT kind,label,status FROM item WHERE id=?", (i,)).fetchone()) == ("task", "issue", "proposed")
        with pytest.raises(PermissionError, match="only add issues"): service.add_item(c, role, "p", "task", "X")
    a = service.add_item(c, "main", "p", "issue", "alias")
    assert tuple(c.execute("SELECT kind,label,status FROM item WHERE id=?", (a,)).fetchone()) == ("task", "issue", "approved")


def test_issue_first_and_label_filter(c):
    t = service.add_item(c, "main", "p", "task", "T", priority="p0")
    i = service.add_item(c, "main", "p", "issue", "I", priority="p3")
    assert [x["id"] for x in service.list_items(c, "p")][:2] == [i, t]
    assert [x["id"] for x in service.list_items(c, "p", label="issue")] == [i]
    assert [x["id"] for x in service.list_items(c, "p", kind="issue")] == [i]
    assert i in [x["id"] for x in service.list_items(c, "p", ready=True)]


def test_set_item_atomic(c, monkeypatch):
    t = service.add_item(c, "main", "p", "task", "T")
    snap = lambda: ([tuple(r) for r in c.execute("SELECT status,priority,version FROM item WHERE id=?", (t,))], c.execute("SELECT count(*) FROM audit").fetchone()[0])
    before = snap()
    def boom(*a, **k): raise RuntimeError("boom")
    monkeypatch.setattr(db, "set_item", boom)
    with pytest.raises(RuntimeError): service.set_item(c, "main", t, "doing", "high")
    assert snap() == before


def test_delete_item(c):
    a, b, d = (service.add_item(c, "main", "p", "task", x) for x in "abd")
    service.dep(c, "main", a, b); service.dep(c, "main", d, a)
    c.execute("INSERT INTO c4_link VALUES('p','obj','item',?)", (a,)); c.commit()
    with pytest.raises(PermissionError): service.delete_item(c, "coder", a)
    with pytest.raises(KeyError): service.delete_item(c, "main", 999)
    service.delete_item(c, "main", a)
    assert not c.execute("SELECT 1 FROM item WHERE id=?", (a,)).fetchone()
    assert not c.execute("SELECT 1 FROM item_dep").fetchone() and not c.execute("SELECT 1 FROM c4_link").fetchone()
    assert c.execute("SELECT count(*) FROM item").fetchone()[0] == 2
    r = c.execute("SELECT after FROM audit WHERE tool='item.delete'").fetchone()
    assert r and '"c4_links": 1' in r[0]


def test_edit_item_all_fields(c):
    t = service.add_item(c, "main", "p", "task", "T")
    service.edit_item(c, "main", t, title="N", body="B", priority="high", spec={"goal": "g"})
    r = c.execute("SELECT title,body,priority,spec FROM item WHERE id=?", (t,)).fetchone()
    assert tuple(r)[:3] == ("N", "B", "high") and "goal" in r[3]


def test_edit_project(c, tmp_path):
    service.add_project(c, "q", "Q", parent="p")
    service.edit_project(c, "q", name="Q2", root=str(tmp_path), docs_dir="docs", description="d")
    r = c.execute("SELECT * FROM project WHERE id='q'").fetchone()
    assert (r["name"], r["root"], r["docs_dir"], r["description"]) == ("Q2", str(tmp_path), str(tmp_path / "docs"), "d")
    assert c.execute("SELECT 1 FROM audit WHERE tool='project.edit'").fetchone()
    for bad in ({"parent": "q"}, {"parent": "nope"}, {"root": "rel"}, {"root": str(tmp_path / "x")}, {"name": " "}, {}):
        with pytest.raises(ValueError): service.edit_project(c, "q", **bad)
    with pytest.raises(ValueError): service.edit_project(c, "p", parent="q")  # cycle
    with pytest.raises(KeyError): service.edit_project(c, "zz", name="x")
    service.edit_project(c, "q", parent="")
    assert c.execute("SELECT parent FROM project WHERE id='q'").fetchone()[0] is None


def test_delete_project_backup(c, tmp_path):
    service.add_item(c, "main", "p", "task", "T")
    with pytest.raises(ValueError): service.delete_project(c, "p", "x")
    assert not (tmp_path / "backups").exists()
    service.delete_project(c, "p", "p")
    b = list((tmp_path / "backups").iterdir()); assert len(b) == 1
    import sqlite3
    assert sqlite3.connect(b[0]).execute("SELECT count(*) FROM item").fetchone()[0] == 1  # backup predates the delete
    assert not c.execute("SELECT 1 FROM project WHERE id='p'").fetchone()
