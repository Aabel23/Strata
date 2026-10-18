import sqlite3, sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from strata import db

@pytest.fixture
def c(tmp_path):
    p = tmp_path / "t.db"
    db.init(p).close()
    db.init(p).close()  # idempotent
    return db.connect(p)

def dec(c, **kw):
    r = dict(project="p", title="t", status="proposed", context="c", decision="quyết định A",
             consequences="x", rejected_options='["B"]')
    r.update(kw)
    c.execute("INSERT INTO decision(project,title,status,context,decision,consequences,rejected_options) "
              "VALUES(:project,:title,:status,:context,:decision,:consequences,:rejected_options)", r)

def hits(c, q):
    return [r["src"] + str(r["ref"]) for r in c.execute("SELECT src,ref FROM search WHERE search MATCH ?", (db.fold(q),))]

def test_decision_immutable(c):
    dec(c)
    with pytest.raises(sqlite3.DatabaseError): c.execute("UPDATE decision SET decision='z'")
    c.execute("UPDATE decision SET status='accepted'")
    with pytest.raises(sqlite3.DatabaseError): c.execute("DELETE FROM decision")

@pytest.mark.parametrize("v", ["", "  ", "[]", None])
def test_rejected_options_required(c, v):
    with pytest.raises(sqlite3.IntegrityError): dec(c, rejected_options=v)

def test_fts_item_lifecycle(c):
    c.execute("INSERT INTO item(project,kind,title,body,status) VALUES('p','note','a','Một quyết định hay','open')")
    assert hits(c, "quyet dinh") == ["item1"]
    c.execute("UPDATE item SET body='khác hẳn'")
    assert hits(c, "quyet dinh") == [] and hits(c, "khac han") == ["item1"]
    c.execute("DELETE FROM item")
    assert hits(c, "khac") == []

def test_fts_decision(c):
    dec(c)
    assert hits(c, "quyet dinh") == hits(c, "quyết định") == ["decision1"]

def test_research_table_gone(c):
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'research%'").fetchone()

def test_init_refuses_nonempty_research(tmp_path):
    p = tmp_path / "old.db"
    x = sqlite3.connect(p); x.execute("CREATE TABLE research(id)"); x.execute("INSERT INTO research VALUES(1)"); x.commit(); x.close()
    with pytest.raises(RuntimeError): db.init(p)

def test_bad_enums(c):
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO item(project,kind,title,status) VALUES('p','bogus','a','open')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO item(project,kind,title,status) VALUES('p','note','a','bogus')")
    with pytest.raises(sqlite3.IntegrityError): dec(c, status="bogus")
