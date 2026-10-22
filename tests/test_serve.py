import json, os, pathlib, subprocess, sys, threading, urllib.error, urllib.request
from urllib.parse import quote
import pytest
from strata import c4_layered, db, server

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests/fixtures/c4_layered"


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"
    c = db.init(p)
    c4_layered.import_dir(c, FIX, "p")
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
    assert st == 200 and set(d) == {"meta", "objects", "connections", "flows", "links", "open_issues", "layered", "contracts", "behavior"}
    assert d["meta"] == {"name": "Demo"} and len(d["objects"]) == 5 and "from" in d["connections"][0] and d["flows"][0]["steps"][0] == {"link": "user_app", "text": "tap"}
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


def test_servable_allowlist(srv, tmp_path):
    code = tmp_path / "code"
    (code / "sub").mkdir(); (code / "sub/n.md").write_text("n"); (code / "FOO.PY").write_text("x")
    for n in ("strata.db-wal", "x.db-journal", "noext"): (code / n).write_text("s")
    (code / "link.py").symlink_to(tmp_path / "secret.txt")
    for bad in ("strata.db-wal", "x.db-journal", ".env", "%2e%2e/secret.txt", "link.py", "sub", "noext", "a.py%00"):
        assert get(srv, "/code/" + bad)[0] == 404, bad
    assert get(srv, "/code/FOO.PY")[0] == 200 and get(srv, "/code/sub/n.md")[0] == 200
    assert server.servable(code, ["sub", "n.md"]) and not server.servable(code, ["sub", ""]) and not server.servable(code, [])


def test_servable_symlink_into_dot_dir(tmp_path):
    (tmp_path / ".secret").mkdir(); (tmp_path / ".secret" / "k.json").write_text("{}")
    (tmp_path / "link.json").symlink_to(tmp_path / ".secret" / "k.json")
    assert server.servable(tmp_path, ["link.json"]) is None


def test_put_page_audited_without_body(tmp_path):
    c = db.init(tmp_path / "d.db")
    db.put_page(c, "p", "s", "T", "note", [{"type": "md", "text": "SECRETBODY"}])
    db.put_page(c, "p", "s", "T", "note", [{"type": "md", "text": "SECRETBODY2"}])
    rs = c.execute("SELECT after FROM audit WHERE tool='page.put' ORDER BY id").fetchall()
    assert [json.loads(r[0])["action"] for r in rs] == ["create", "update"]
    assert "SECRETBODY" not in json.dumps([tuple(r) for r in c.execute("SELECT * FROM audit")])


def test_mermaid_labels_escaped():
    js = (ROOT / "viewer/page.js").read_text()
    assert 'securityLevel:"loose"' in js
    for ch in ('"#35;"', '"#quot;"', '"#lt;"', '"#gt;"'): assert ch in js
    assert "lines(n.text" in js and "lines(s.text" in js and "lines(l)" in js
