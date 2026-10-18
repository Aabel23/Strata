import sqlite3
import pytest
from strata import db
from strata.blocks import page_text


@pytest.fixture
def c(tmp_path):
    db.init(tmp_path / "t.db").close()
    return db.connect(tmp_path / "t.db")


def hits(c, q):
    return [r["src"] + str(r["ref"]) for r in c.execute("SELECT src,ref FROM search WHERE search MATCH ?", (db.fold(q),))]


B = [{"type": "md", "text": "Một quyết định hay"}, {"type": "table", "head": ["đầu"], "rows": [["ô"]]}]


def test_page_text_collects_strings_not_types():
    t = page_text(B)
    assert "Một quyết định hay" in t and "đầu" in t and "md" not in t.split("\n")


def test_roundtrip_and_text(c):
    db.put_page(c, "p", "s", "Tiêu đề", "note", B)
    pg = db.get_page(c, "p", "s")
    assert pg["blocks"] == B and pg["title"] == "Tiêu đề" and pg["updated_at"]
    assert c.execute("SELECT text FROM page").fetchone()[0] == page_text(B)
    assert db.get_page(c, "p", "zz") is None


def test_list_pages(c):
    db.put_page(c, "p", "a", "A", "note", [])
    db.put_page(c, "q", "b", "B", "research", [])
    assert [x["slug"] for x in db.list_pages(c)] == ["a", "b"]
    assert [x["slug"] for x in db.list_pages(c, "q")] == ["b"]
    assert "blocks" not in db.list_pages(c)[0]


def test_fts_lifecycle(c):
    db.put_page(c, "p", "s", "Tiêu đề", "note", B)
    assert hits(c, "quyet dinh") == ["page1"] and hits(c, "tieu de") == ["page1"] and hits(c, "dau") == ["page1"]
    db.put_page(c, "p", "s", "Tiêu đề", "note", [{"type": "md", "text": "khác hẳn"}])  # upsert keeps rowid
    assert hits(c, "quyet dinh") == [] and hits(c, "khac han") == ["page1"]
    c.execute("DELETE FROM page"); c.commit()
    assert hits(c, "khac") == []


def test_constraints(c):
    with pytest.raises(sqlite3.IntegrityError): db.put_page(c, "p", "s", "t", "bogus", [])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO page(project,slug,title,kind,blocks) VALUES('p','s','t','note','not json')")
