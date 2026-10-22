import json, sqlite3
from conftest import run


def test_coverage_cli(tmp_path, dbp):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.py").write_text("x = 1\n"); (src / "b.py").write_text("y = 1\n")
    assert run(dbp, "project", "add", "p", "--name", "P", "--root", str(tmp_path), "--db", str(dbp))[0] == 0
    con = sqlite3.connect(dbp)
    con.execute("INSERT INTO c4_object(project,id,name,type,owns) VALUES('p','o','O','component',?)", (json.dumps(["src/a.py"]),)); con.commit(); con.close()
    rc, out = run(dbp, "c4", "coverage", "--project", "p", "--db", str(dbp))
    assert rc == 0 and "src/\n  b.py" in out and "a.py" not in out and out.strip().endswith("1 files unowned in 1 directories")
    assert json.loads(run(dbp, "c4", "coverage", "--project", "p", "--json", "--db", str(dbp))[1]) == {"src": ["b.py"]}
