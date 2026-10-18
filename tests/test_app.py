import json, pathlib, subprocess, sys, threading, urllib.error, urllib.request
import pytest
from strata import db, server

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "strata.py")]


def cli(dbp, *args):
    r = subprocess.run([*CLI, *args, "--db", str(dbp)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def mkdocs(tmp_path):
    d = tmp_path / "docs"
    (d / "research").mkdir(parents=True); (d / "assets").mkdir(); (d / "plan/archive").mkdir(parents=True); (d / ".hid").mkdir()
    (d / "research/a.html").write_text("<html><head><title>Nghiên cứu đồ thị</title><style>x{}</style></head><body><h1>H</h1><p>Nội dung <b>đặc biệt</b></p><script>var z=1</script></body></html>")
    (d / "b.html").write_text("<body><h1>Chỉ có h1</h1></body>")
    (d / "plan/c.html").write_text("<title>Kế hoạch</title>")
    (d / "assets/x.html").write_text("<title>skip</title>"); (d / "plan/archive/y.html").write_text("<title>skip</title>"); (d / ".hid/z.html").write_text("<title>skip</title>")
    (d / "assets/s.css").write_text("body{}"); (d / ".env").write_text("secret"); (d / "x.db").write_text("s")
    (tmp_path / "secret.txt").write_text("secret")
    return d


@pytest.fixture
def env(tmp_path):
    p = tmp_path / "t.db"; d = mkdocs(tmp_path)
    assert cli(p, "project", "add", "g", "--name", "Group")[0] == 0
    assert cli(p, "project", "add", "a", "--name", "A", "--root", str(tmp_path), "--docs-dir", "docs", "--parent", "g")[0] == 0
    assert cli(p, "doc", "scan", "--project", "a")[0] == 0
    cli(p, "item", "add", "--project", "a", "--kind", "task", "--title", "làm đồ thị", "--status", "doing")
    cli(p, "item", "add", "--project", "a", "--kind", "issue", "--title", "lỗi đăng nhập")
    c = db.connect(p)
    c.execute("INSERT INTO decision(project,title,status,decision,rejected_options) VALUES('a','Chọn SQLite','accepted','dùng sqlite','[\"pg\"]')")
    db.put_page(c, "a", "s", "Thảo luận đồ thị", "note", [{"type": "md", "text": "bàn về đồ thị"}]); c.commit()
    s = server.make_server(p, None, 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", p, d
    s.shutdown(); s.server_close()


def get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""


def J(env, path): return json.loads(get(env[0], path)[1])


def test_cli_project_doc_item_audit(env):
    b, p, d = env
    c = db.connect(p)
    assert [r["id"] for r in c.execute("SELECT id FROM project ORDER BY id")] == ["a", "g"]
    docs = {r["path"]: dict(r) for r in c.execute("SELECT * FROM doc")}
    assert set(docs) == {"research/a.html", "b.html", "plan/c.html"}  # assets, plan/archive, dotdirs skipped
    assert docs["research/a.html"]["title"] == "Nghiên cứu đồ thị" and docs["research/a.html"]["kind"] == "research"
    assert docs["b.html"]["title"] == "Chỉ có h1" and docs["b.html"]["kind"] == "other"
    assert "đặc biệt" in docs["research/a.html"]["text"] and "var z" not in docs["research/a.html"]["text"] and "x{}" not in docs["research/a.html"]["text"]
    # idempotent rescan; vanished file -> missing; back again -> current
    cli(p, "doc", "scan", "--project", "a"); assert c.execute("SELECT count(*) FROM doc").fetchone()[0] == 3
    (d / "b.html").unlink(); cli(p, "doc", "scan", "--project", "a")
    assert c.execute("SELECT status FROM doc WHERE path='b.html'").fetchone()[0] == "missing"
    (d / "b.html").write_text("<h1>Lại có</h1>"); cli(p, "doc", "scan", "--project", "a")
    assert c.execute("SELECT status FROM doc WHERE path='b.html'").fetchone()[0] == "current"
    assert cli(p, "doc", "set", "--project", "a", "b.html", "--feature", "F", "--status", "draft", "--ord", "3")[0] == 0
    assert dict(c.execute("SELECT feature,status,ord FROM doc WHERE path='b.html'").fetchone()) == {"feature": "F", "status": "draft", "ord": 3}
    assert cli(p, "doc", "set", "--project", "a", "nope.html", "--ord", "1")[0] == 1
    cli(p, "item", "set", "1", "--status", "done")
    assert c.execute("SELECT status,version FROM item WHERE id=1").fetchone()[:] == ("done", 2)
    assert cli(p, "item", "set", "99", "--status", "done")[0] == 1
    tools = {r[0] for r in c.execute("SELECT tool FROM audit")}
    assert {"project.add", "doc.scan", "doc.set", "item.add", "item.set"} <= tools
    assert c.execute("SELECT count(*) FROM audit WHERE tool='project.add'").fetchone()[0] == 2
    assert cli(p, "item", "add", "--project", "a", "--kind", "bogus", "--title", "x")[0] != 0
    assert cli(p, "project", "add", "a", "--name", "dup")[0] == 1


def test_api_projects_and_filters(env):
    ps = {x["id"]: x for x in J(env, "/api/projects")}
    assert ps["a"]["parent"] == "g" and ps["a"]["tasks"] == {"doing": 1} and ps["a"]["issues_open"] == 1
    assert ps["a"]["pages"] == 1 and ps["a"]["docs"] == 3 and ps["a"]["decisions"] == 1 and ps["a"]["last_update"]
    assert [x["kind"] for x in J(env, "/api/items?project=a")] == ["task", "issue"]
    assert [x["title"] for x in J(env, "/api/items?project=a&kind=issue")] == ["lỗi đăng nhập"]
    assert J(env, "/api/items?status=done") == [] and len(J(env, "/api/items?id=1")) == 1
    assert [x["title"] for x in J(env, "/api/decisions?project=a")] == ["Chọn SQLite"]
    assert len(J(env, "/api/docs?project=a")) == 3 and J(env, "/api/docs?project=zz") == []
    assert "text" not in J(env, "/api/docs?project=a")[0]
    assert len(J(env, "/api/audit?project=a&limit=2")) == 2


@pytest.mark.parametrize("path", ["/api/items?kind=bogus", "/api/items?status=x", "/api/items?id=1%20OR%201", "/api/audit?limit=0", "/api/audit?limit=501",
                                  "/api/audit?limit=x", "/api/search", "/api/search?q=", "/api/search?q=%22%20*%28"])
def test_api_400(env, path):
    assert get(env[0], path)[0] == 400


def test_search_across_sources(env):
    got = {(h["src"], h["key"]) for h in J(env, "/api/search?q=do%20thi")}
    assert {("item", "task"), ("page", "s"), ("doc", "research/a.html")} <= got
    assert [h["src"] for h in J(env, "/api/search?q=dang%20nhap")] == ["item"]
    h = J(env, "/api/search?q=sqlite&project=a")[0]
    assert h["src"] == "decision" and h["title"] == "Chọn SQLite" and h["project"] == "a" and "snippet" in h
    assert J(env, "/api/search?q=sqlite&project=g") == []
    assert J(env, "/api/search?q=%C4%91%E1%BB%93")  # "đồ" folded like the index
    assert J(env, "/api/search?q=zzzz") == [] and get(env[0], "/api/search?q=%22%20OR%20x")[0] == 200  # FTS syntax is neutralised


def test_docs_serving_and_blocking(env):
    b = env[0]
    assert get(b, "/docs/a/research/a.html")[0] == 200 and get(b, "/docs/a/assets/s.css") == (200, b"body{}")
    for bad in ("/docs/a/.env", "/docs/a/x.db", "/docs/a/.hid/z.html", "/docs/a/../secret.txt", "/docs/a/%2e%2e/secret.txt", "/docs/a/..%2fsecret.txt",
                "/docs/a//etc/passwd", "/docs/zz/b.html", "/docs/g/b.html", "/docs/a/", "/docs/a", "/docs/a/%00x"):
        assert get(b, bad)[0] == 404, bad


def test_shell_routes(env):
    b = env[0]
    st, body = get(b, "/")
    assert st == 200 and b"/app.js" in body and b"/api/c4" not in body
    assert b"/api/c4" in get(b, "/c4")[1]
    for ok in ("/app.js", "/app.css", "/pages", "/page/a/s", "/page.js"): assert get(b, ok)[0] == 200, ok
    assert b"/c4?project=" in get(b, "/page.js")[1]


def test_assets_route(env):
    b = env[0]
    st, body = get(b, "/assets/hero-mountains.svg")
    assert st == 200 and body.startswith(b"<svg")
    for bad in ("/assets/../app.js", "/assets/%2e%2e/app.js", "/assets/..%2fapp.js", "/assets/nope.svg", "/assets/a/b"):
        assert get(b, bad)[0] == 404, bad


def test_app_js_never_injects_html():
    js = (ROOT / "viewer/app.js").read_text()
    assert not any(w in js for w in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", "outerHTML"))
