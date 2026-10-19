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
    assert st == 200 and set(d) == {"meta", "objects", "connections", "flows", "issues", "links", "open_issues"}
    assert d["meta"]["name"] == "project1_app" and "security" in d["meta"]["tags"]
    assert len(d["objects"]) == 115 and "interfaces" in d["objects"][0] and "from" in d["connections"][0] and d["flows"][0]["steps"][1] == {"connection": "fm_c1", "text": "generation++, busy=true"}
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


def test_api_c4_issues(srv):
    d = json.loads(get(srv, "/api/c4?project=p")[1])
    assert isinstance(d["issues"], dict) and "root" not in d
    assert all(c in ("dead_link", "no_link", "no_desc") for v in d["issues"].values() for c in v)


def raw(port, host, path="/api/projects"):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port); c.putrequest("GET", path, skip_host=True)
    if host is not None: c.putheader("Host", host)
    c.endheaders(); return c.getresponse().status


def test_search_params(srv):
    assert get(srv, "/api/search?q=a&src=foo")[0] == 400
    assert get(srv, "/api/search?q=a&limit=abc")[0] == 400
    assert get(srv, "/api/search?q=a&limit=1000&src=item&project=p")[0] == 200
    assert get(srv, "/api/search?q=")[0] == 400


def test_host_check(dbp):
    s = server.make_server(dbp, "p", 0, "127.0.0.1", allow_hosts=["Box.ts"], bound_hosts=["127.0.0.1", "100.1.2.3"])
    threading.Thread(target=s.serve_forever, daemon=True).start()
    port = s.server_address[1]
    try:
        assert raw(port, f"evil.com:{port}") == 403 and raw(port, None) == 403 and raw(port, f"127.0.0.1:{port + 1}") == 403
        for h in (f"127.0.0.1:{port}", f"LOCALHOST:{port}", f"100.1.2.3:{port}", f"box.ts:{port}", "box.ts"): assert raw(port, h) == 200, h
    finally: s.shutdown(); s.server_close()


def test_bind_all_needs_allow_host(dbp):
    for h in ("0.0.0.0", "::"):
        with pytest.raises(ValueError, match="allow-host"): server.make_server(dbp, "p", 0, h)


def test_autoscan_no_audit_and_keeps_doc_state(dbp, tmp_path):
    d = tmp_path / "docs"; d.mkdir(); (d / "a.md").write_text("# A\nx")
    c = db.connect(dbp); db.add_project(c, "q", "Q", docs_dir=str(d))
    s = server.make_server(dbp, "p", 0); threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    try:
        assert get(base, "/api/docs?project=q")[0] == 200
        assert c.execute("SELECT count(*) FROM audit WHERE tool='doc.scan'").fetchone()[0] == 0
        db.set_doc(c, "q", "a.md", feature="f", status="draft", ord=3)
        get(base, "/api/docs?project=q")
        (d / "a.md").unlink(); get(base, "/api/docs?project=q")
        assert c.execute("SELECT status FROM doc WHERE path='a.md'").fetchone()[0] == "missing"
        (d / "a.md").write_text("# A\nx"); get(base, "/api/docs?project=q")
        assert tuple(c.execute("SELECT feature,status,ord FROM doc WHERE path='a.md'").fetchone()) == ("f", "draft", 3)
    finally: s.shutdown(); s.server_close()
