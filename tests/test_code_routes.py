import json, shutil, threading, urllib.request, urllib.error
import pytest
from strata import c4_layered as L, db, server
from conftest import FIX

PY = "class A:\n    def m(self):\n        return 1\n"


@pytest.fixture
def hp(tmp_path):
    d = tmp_path / "c4"; shutil.copytree(FIX, d)
    (d / "map.yaml").write_text((d / "map.yaml").read_text().replace("root: .", "root: ..").replace('owns: ["src/**"]', 'owns: ["src/**", "nope/*.py"]'))
    s = tmp_path / "src"; s.mkdir()
    (s / "a.py").write_text(PY); (s / "bad.py").write_text("def (:\n"); (s / "x.dart").write_text("x\n")
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P", root=str(tmp_path)); L.import_dir(c, d, "p"); c.close()
    srv = server.make_server(p, None, 0); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown(); srv.server_close()


def get(hp, path):
    try:
        with urllib.request.urlopen("http://" + hp + path) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_files(hp):
    st, r = get(hp, "/api/code/files?project=p&object=relay")
    assert st == 200 and {"src/a.py", "src/bad.py"} <= {f["path"] for f in r["files"]} and r["missing"] == ["nope/*.py"]
    assert get(hp, "/api/code/files?project=p&object=zzz")[0] == 404
    assert get(hp, "/api/code/files?project=p")[0] == 400


def test_symbols(hp):
    st, r = get(hp, "/api/code/symbols?project=p&path=src/a.py")
    assert st == 200 and r["loc"] == 3 and {s["id"] for s in r["symbols"]} == {"src/a.py::A", "src/a.py::A.m"}
    assert get(hp, "/api/code/symbols?project=p&path=src/bad.py")[1]["error"] == "syntax error"
    assert get(hp, "/api/code/symbols?project=p&path=src/x.dart")[1]["symbols"] == []
    assert get(hp, "/api/code/symbols?project=p&path=../x")[0] == 400
    assert get(hp, "/api/code/symbols?project=p&path=src/none.py")[0] == 404


def test_src(hp):
    st, r = get(hp, "/api/code/src?project=p&id=src/a.py::A.m")
    assert st == 200 and "return 1" in r["text"]
    assert get(hp, "/api/code/src?project=p&id=nocolons")[0] == 400
    assert get(hp, "/api/code/src?project=p&id=../x.py::A")[0] == 400
    assert get(hp, "/api/code/src?project=p&id=src/a.py::Nope")[0] == 404
    assert get(hp, "/api/code/src?project=p&id=src/none.py::A")[0] == 404
    assert get(hp, "/api/code/other?project=p")[0] == 404
    assert get(hp, "/api/c4?project=p")[0] == 200
