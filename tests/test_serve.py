import json, os, pathlib, subprocess, sys, threading, urllib.error, urllib.request
from urllib.parse import quote
import pytest
from strata import c4, db, server

ROOT = pathlib.Path(__file__).resolve().parent.parent
EX = ROOT / "examples/project1_app.strata.yaml"


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"
    c = db.init(p)
    c4.import_yaml(c, EX, "p")
    return p


@pytest.fixture
def srv(dbp, tmp_path):
    # point the code root at a temp dir with a file and a secret outside it
    (tmp_path / "code").mkdir()
    (tmp_path / "code/a.py").write_text("print(1)")
    (tmp_path / "secret.txt").write_text("secret")
    c = db.connect(dbp)
    c.execute("UPDATE c4_meta SET root=?", (str(tmp_path / "code"),)); c.commit()
    s = server.make_server(dbp, "p", 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown(); s.server_close()


def test_code_hides_dotfiles_and_dbs(srv, tmp_path):
    for n in (".env", "x.db", "x.sqlite3"): (tmp_path / "code" / n).write_text("s")
    (tmp_path / "code/.git").mkdir(); (tmp_path / "code/.git/config").write_text("s")
    for n in (".env", "x.db", "x.sqlite3", ".git/config"): assert get(srv, "/code/" + n)[0] == 404, n


def get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""


def test_api_c4_shape(srv):
    st, body = get(srv, "/api/c4?project=p")
    d = json.loads(body)
    assert st == 200 and set(d) == {"meta", "objects", "connections", "flows"}
    assert d["meta"]["name"] == "project1_app" and "security" in d["meta"]["tags"]
    assert len(d["objects"]) == 14 and "from" in d["connections"][0] and d["flows"][0]["steps"][0]["connection"] == "app_req"
    assert json.loads(get(srv, "/api/c4")[1]) == d  # default project


def test_unknown_project_404(srv):
    assert get(srv, "/api/c4?project=zz")[0] == 404


def test_index_and_vendor(srv):
    st, body = get(srv, "/c4")
    assert st == 200 and b"js-yaml" not in body and b"/api/c4" in body
    assert get(srv, "/vendor/dagre.min.js")[0] == 200


def test_code_and_traversal(srv):
    assert get(srv, "/code/a.py") == (200, b"print(1)")
    for bad in ("/code/../secret.txt", "/code/%2e%2e/secret.txt", "/code/..%2fsecret.txt", "/code//etc/passwd"):
        assert get(srv, bad)[0] == 404, bad
