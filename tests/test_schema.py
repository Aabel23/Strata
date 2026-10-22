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

def hits(c, q):
    return [r["src"] + str(r["ref"]) for r in c.execute("SELECT src,ref FROM search WHERE search MATCH ?", (db.fold(q),))]

def test_fts_item_lifecycle(c):
    c.execute("INSERT INTO item(project,kind,title,body,status) VALUES('p','note','a','Một quyết định hay','open')")
    assert hits(c, "quyet dinh") == ["item1"]
    c.execute("UPDATE item SET body='khác hẳn'")
    assert hits(c, "quyet dinh") == [] and hits(c, "khac han") == ["item1"]
    c.execute("DELETE FROM item")
    assert hits(c, "khac") == []

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


def test_old_decision_schema_migrates(tmp_path):
    p = tmp_path / "old.db"
    x = sqlite3.connect(p)
    x.executescript("""
    CREATE TABLE decision(id INTEGER PRIMARY KEY, project TEXT, title TEXT, rejected_options TEXT);
    CREATE TRIGGER decision_no_delete BEFORE DELETE ON decision BEGIN SELECT RAISE(ABORT,'append-only'); END;
    CREATE TABLE c4_link(project TEXT NOT NULL, object_id TEXT NOT NULL,
      ref_kind TEXT NOT NULL CHECK(ref_kind IN ('item','decision')), ref_id INTEGER NOT NULL,
      PRIMARY KEY(project,object_id,ref_kind,ref_id));
    CREATE VIRTUAL TABLE search USING fts5(title,body,src UNINDEXED,ref UNINDEXED,project UNINDEXED);
    INSERT INTO search VALUES('t','b','decision',1,'p');
    INSERT INTO decision VALUES(1,'p','t','[1]');
    INSERT INTO c4_link VALUES('p','o','item',7),('p','o','decision',1);""")
    x.commit(); x.close()
    for _ in range(2):  # second run: idempotent
        db.init(p).close()
    c = db.connect(p)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'decision%'").fetchone()
    assert [tuple(r) for r in c.execute("SELECT ref_kind,ref_id FROM c4_link")] == [("item", 7)]
    with pytest.raises(sqlite3.IntegrityError): c.execute("INSERT INTO c4_link VALUES('p','o','decision',1)")

def test_audit_append_only(c):
    c.execute("INSERT INTO audit(tool) VALUES('x')")
    for sql in ("UPDATE audit SET tool='y'", "DELETE FROM audit"):
        with pytest.raises(sqlite3.DatabaseError):
            c.execute(sql)
    assert c.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
