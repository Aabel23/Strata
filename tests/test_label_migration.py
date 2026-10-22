import sqlite3, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from strata import db

OLD = """CREATE TABLE item(id INTEGER PRIMARY KEY, project TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('rule','task','issue','knowledge','draft','note','step','gate')),
  title TEXT NOT NULL, body TEXT,
  status TEXT NOT NULL CHECK(status IN ('proposed','approved','open','doing','review','done','rejected')),
  priority TEXT, spec JSON CHECK(spec IS NULL OR json_valid(spec)), always_load INT NOT NULL DEFAULT 0, core INT NOT NULL DEFAULT 0,
  owner TEXT, claimed_at TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, version INT NOT NULL DEFAULT 1, phase INT, roadmap TEXT);
CREATE TABLE item_dep(item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE, PRIMARY KEY(item_id,depends_on));"""

def test_issue_becomes_labelled_task(tmp_path):
    p = tmp_path / "o.db"
    x = sqlite3.connect(p); x.executescript(OLD)
    x.executemany("INSERT INTO item(id,project,kind,title,status) VALUES(?,?,?,?,?)",
                  [(1, "p", "issue", "Lỗi relay", "open"), (2, "p", "issue", "done one", "done"), (3, "p", "task", "t", "open")])
    x.execute("INSERT INTO item_dep VALUES(3,1)"); x.commit(); x.close()
    for _ in range(2):  # idempotent
        db.init(p).close()
    c = db.connect(p)
    assert [tuple(r) for r in c.execute("SELECT id,kind,label,status FROM item ORDER BY id")] == \
        [(1, "task", "issue", "approved"), (2, "task", "issue", "done"), (3, "task", None, "open")]
    assert c.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 1
    assert "'issue'" not in c.execute("SELECT sql FROM sqlite_master WHERE name='item'").fetchone()[0]
    assert [r["ref"] for r in c.execute("SELECT ref FROM search WHERE search MATCH 'relay' AND src='item'")] == [1]
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.execute("DELETE FROM item WHERE id=1")  # FK cascade still points at item
    assert c.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 0

def test_add_item_issue_alias_and_order(tmp_path):
    c = db.init(tmp_path / "n.db")
    assert "label" in [r[1] for r in c.execute("PRAGMA table_info(item)")]
    db.add_project(c, "p", "P")
    a = db.add_item(c, "p", "task", "a", priority="high"); b = db.add_item(c, "p", "issue", "b", priority="low")
    assert tuple(c.execute("SELECT kind,label FROM item WHERE id=?", (b,)).fetchone()) == ("task", "issue")
    assert [r[0] for r in c.execute(f"SELECT id FROM item ORDER BY {db.ITEM_ORDER}")] == [b, a]
