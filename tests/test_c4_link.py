import json, threading, urllib.request
import pytest
from strata import db, server
from test_c4 import EX, run


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"
    assert run(p, "import-yaml", str(EX), "--project", "p")[0] == 0
    run(p, "item", "add", "--project", "p", "--kind", "issue", "--title", "Lỗi relay")   # item 1
    run(p, "item", "add", "--project", "p", "--kind", "task", "--title", "Làm mail")      # item 2
    c = db.connect(p)
    c.execute("INSERT INTO decision(project,title,status,rejected_options,created_at) VALUES('p','Dùng HPKE','accepted','[\"x\"]','t')"); c.commit()
    return p


def audits(p, tool): return db.connect(p).execute("SELECT count(*) FROM audit WHERE tool=?", (tool,)).fetchone()[0]


def test_link_unlink_audit_and_dup(dbp):
    assert run(dbp, "c4", "link", "--project", "p", "--object", "relay", "--item", "1")[0] == 0
    assert run(dbp, "c4", "link", "--project", "p", "--object", "relay", "--item", "1") == (0, "no change\n")
    assert run(dbp, "c4", "link", "--project", "p", "--object", "relay", "--decision", "1")[0] == 0
    assert audits(dbp, "c4.link") == 2
    code, out = run(dbp, "c4", "links", "--project", "p", "--object", "relay")
    assert code == 0 and "Lỗi relay" in out and "Dùng HPKE" in out
    l = db.links_for(db.connect(dbp), "p", "relay")
    assert l["items"] == [{"id": 1, "kind": "issue", "title": "Lỗi relay", "status": "open"}]
    assert l["decisions"][0]["title"] == "Dùng HPKE"
    assert run(dbp, "c4", "unlink", "--project", "p", "--object", "relay", "--item", "1")[0] == 0
    assert run(dbp, "c4", "unlink", "--project", "p", "--object", "relay", "--item", "1")[1] == "no change\n"
    assert audits(dbp, "c4.unlink") == 1


@pytest.mark.parametrize("args", [
    ["--object", "nope", "--item", "1"], ["--object", "relay", "--item", "99"], ["--object", "relay", "--decision", "99"],
    ["--object", "relay"], ["--object", "relay", "--item", "1", "--decision", "1"]])
def test_link_errors(dbp, args):
    code, out = run(dbp, "c4", "link", "--project", "p", *args)
    assert code == 1 and out.startswith("ERROR")
    assert audits(dbp, "c4.link") == 0


def test_api_links_and_open_issues(dbp):
    run(dbp, "c4", "link", "--project", "p", "--object", "relay", "--item", "1")
    run(dbp, "c4", "link", "--project", "p", "--object", "mail", "--item", "2")   # a task: not an issue
    s = server.make_server(dbp, "p", 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{s.server_address[1]}/api/c4?project=p"
    try:
        d = json.load(urllib.request.urlopen(url))
        assert d["open_issues"] == ["relay"] and set(d["links"]) == {"relay", "mail"}
        assert d["links"]["relay"]["items"][0]["id"] == 1
        run(dbp, "item", "set", "1", "--status", "done")
        assert json.load(urllib.request.urlopen(url))["open_issues"] == []
    finally: s.shutdown(); s.server_close()
