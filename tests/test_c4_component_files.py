import json, sqlite3
import pytest
from conftest import run
from strata import c4_layered as L


def setup(tmp_path, dbp, owns):
    for d in ("src/sub", "src/.hid", "src/venv", ".git"): (tmp_path / d).mkdir(parents=True)
    for f in ("src/a.py", "src/b.js", "src/sub/c.css", "src/notes.txt", "src/.hid/x.py", "src/venv/y.py", ".git/z.py"): (tmp_path / f).write_text("x\n")
    assert run(dbp, "project", "add", "p", "--name", "P", "--root", str(tmp_path), "--db", str(dbp))[0] == 0
    con = sqlite3.connect(dbp); con.row_factory = sqlite3.Row
    con.execute("INSERT INTO c4_meta(project,name,root) VALUES('p','P',?)", (str(tmp_path),))
    con.execute("INSERT INTO c4_object(project,id,name,type,owns) VALUES('p','o','O','component',?)", (json.dumps(owns) if owns is not None else None,))
    con.execute("INSERT INTO c4_object(project,id,name,type) VALUES('p','n','N','component')"); con.commit()
    return con


def paths(r): return [f["path"] for f in r["files"]]


def test_glob_dir_missing_filters(tmp_path, dbp):
    c = setup(tmp_path, dbp, ["src/*.py", "src/sub", "nope/*.py", "src"])
    r = L.component_files(c, "p", "o")
    assert paths(r) == ["src/a.py", "src/b.js", "src/sub/c.css"]  # txt, hidden, venv excluded
    assert r["missing"] == ["nope/*.py"] and not r["truncated"] and r["root"] == str(tmp_path) and r["object"] == "o"
    assert all(f["exists"] for f in r["files"])


def test_cap(tmp_path, dbp, monkeypatch):
    c = setup(tmp_path, dbp, ["src"]); monkeypatch.setattr(L, "FILE_CAP", 2)
    r = L.component_files(c, "p", "o")
    assert paths(r) == ["src/a.py", "src/b.js"] and r["truncated"]


def test_unknown_and_no_owns(tmp_path, dbp):
    c = setup(tmp_path, dbp, None)
    assert L.component_files(c, "p", "n") == {"object": "n", "root": str(tmp_path), "files": [], "missing": [], "truncated": False}
    assert L.component_files(c, "p", "o")["files"] == []
    with pytest.raises(KeyError): L.component_files(c, "p", "zz")
    with pytest.raises(KeyError): L.component_files(c, "q", "o")
