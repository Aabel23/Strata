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
    cli(p, "item", "set", "1", "--status", "approved")  # release
    assert c.execute("SELECT status,version FROM item WHERE id=1").fetchone()[:] == ("approved", 2)
    assert cli(p, "item", "set", "99", "--status", "done")[0] == 1
    tools = {r[0] for r in c.execute("SELECT tool FROM audit")}
    assert {"project.add", "doc.scan", "doc.set", "item.add", "item.transition"} <= tools
    assert c.execute("SELECT count(*) FROM audit WHERE tool='project.add'").fetchone()[0] == 2
    assert cli(p, "item", "add", "--project", "a", "--kind", "bogus", "--title", "x")[0] != 0
    assert cli(p, "project", "add", "a", "--name", "dup")[0] == 1


def test_api_projects_and_filters(env):
    ps = {x["id"]: x for x in J(env, "/api/projects")}
    assert ps["a"]["parent"] == "g" and ps["a"]["tasks"] == {"doing": 1} and ps["a"]["issues_open"] == 1
    assert ps["a"]["pages"] == 1 and ps["a"]["docs"] == 3 and ps["a"]["last_update"]
    assert [x["kind"] for x in J(env, "/api/items?project=a")] == ["task", "issue"]
    assert [x["title"] for x in J(env, "/api/items?project=a&kind=issue")] == ["lỗi đăng nhập"]
    assert J(env, "/api/items?status=done") == [] and len(J(env, "/api/items?id=1")) == 1
    assert get(env[0], "/api/decisions")[0] == 404
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
    h = J(env, "/api/search?q=do%20thi&project=a")[0]
    assert h["project"] == "a" and "snippet" in h and "decision" not in {x["src"] for x in J(env, "/api/search?q=sqlite")}
    assert J(env, "/api/search?q=do%20thi&project=g") == []
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


def test_roadmap_astra_frontend():
    app_js = (ROOT / "viewer/app.js").read_text()
    app_css = (ROOT / "viewer/app.css").read_text()
    roadmap_js = (ROOT / "viewer/roadmap.js").read_text()
    assert "renderDetail" in app_js and "ltFormat" in app_js
    assert "camps[0].cur" in app_js and "ph=" in app_js
    assert "lt-mapbox" in app_css and ".lt .detail" in app_css and ".lt .thread" in app_css
    assert "--st-miss:#c98a6a" in app_css or "--st-miss: #c98a6a" in app_css
    assert "[330," in roadmap_js and "top-24" in roadmap_js


def test_docs_autoscan_md(env):
    b, p, d = env
    (d / "guide.md").write_text("Intro\n\n# Hướng dẫn đặc biệt\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    docs = {x["path"]: x for x in J(env, "/api/docs?project=a")}  # no `doc scan`: server picks it up
    assert docs["guide.md"]["title"] == "Hướng dẫn đặc biệt" and docs["guide.md"]["status"] == "current"
    assert get(b, "/docs/a/guide.md")[0] == 200
    n = db.connect(p).execute("SELECT count(*) FROM audit WHERE tool='doc.scan'").fetchone()[0]
    J(env, "/api/docs?project=a")  # unchanged dir: no rescan, no new audit row
    assert db.connect(p).execute("SELECT count(*) FROM audit WHERE tool='doc.scan'").fetchone()[0] == n
    (d / "guide.md").unlink()
    assert {x["path"]: x for x in J(env, "/api/docs?project=a")}["guide.md"]["status"] == "missing"


def test_yaml_doc_codetree_and_api(env):
    b, p, d = env
    (d / "strata").mkdir()
    (d / "strata/flow.yaml").write_text("title: Luồng\nsummary: tóm tắt\nblocks:\n  - md: '## Hi đặc biệt'\n"
                                        "  - diagram: {nodes: [{id: a}, {id: b, link: x}], edges: [[a, b, nhãn]]}\n")
    (d / "bad.yaml").write_text("title: Hỏng\ncode: src/x.py\nblocks:\n  - diagram: {nodes: [{id: a}], edges: [[a, z]]}\n  - nope: 1\n")
    docs = {x["path"]: x for x in J(env, "/api/docs?project=a")}
    assert docs["strata/flow.yaml"]["title"] == "Luồng" and json.loads(docs["strata/flow.yaml"]["code"]) == []  # code: is metadata, never inferred
    assert json.loads(docs["bad.yaml"]["code"]) == ["src/x.py"]
    ok = J(env, "/api/doc?project=a&path=strata/flow.yaml")
    assert ok["errors"] == [] and [x["type"] for x in ok["blocks"]] == ["md", "diagram"] and ok["blocks"][0]["text"] == "## Hi đặc biệt"
    bad = J(env, "/api/doc?project=a&path=bad.yaml")["errors"]
    assert any("unknown node 'z'" in e for e in bad) and any("unknown type 'nope'" in e for e in bad)
    assert "Luồng" in [h["title"] for h in J(env, "/api/search?q=dac%20biet&project=a")]
    for bad_path in ("../secret.txt", "b.html", ".hid/z.yaml", "nope.yaml"):
        assert get(b, "/api/doc?project=a&path=" + bad_path)[0] == 404


def test_swimlane_block_validates():
    from strata.blocks import load_doc
    ok = """title: t
blocks:
  - swimlane:
      lanes: {A: [x, y]}
      phases: [p1, p2]
      steps:
        - {lane: x, text: a}
        - {lane: y, text: [b, c], phase: 2, data: [1]}
"""
    assert load_doc(ok)[1] == []
    bad = ok.replace("lane: y", "lane: z").replace("data: [1]", "data: [5]")
    errs = load_doc(bad)[1]
    assert any("lane 'z'" in m for m in errs) and any("step 5" in m for m in errs)


def test_statemachine_roadmap_validate():
    from strata.blocks import load_doc
    sm = """title: t
blocks:
  - statemachine:
      states: [a, {id: b, tone: ok}]
      initial: a
      final: b
      transitions: [[a, a, loop], [a, b]]
  - roadmap:
      periods: [Q1, Q2]
      lanes: [L]
      items: [{lane: L, text: x, from: Q1, to: Q2, status: done}]
      milestones: [{at: Q2, text: v1}]
"""
    assert load_doc(sm)[1] == []
    bad = load_doc(sm.replace("final: b", "final: [z]").replace("tone: ok", "tone: red").replace("[a, b]]", "[a, q]]").replace("dir", "dir")
                   .replace("states: [a,", "dir: UP\n      states: [a, a,"))[1]
    for m in ("unknown state 'z'", "tone must be", "unknown state 'q'", "dir must be", "duplicate id 'a'"):
        assert any(m in x for x in bad), (m, bad)
    bad = load_doc(sm.replace("lane: L", "lane: M").replace("to: Q2", "to: Q0").replace("done", "x").replace("at: Q2", "at: Q9"))[1]
    for m in ("lane 'M'", "to 'Q0'", "status must be", "at 'Q9'"):
        assert any(m in x for x in bad), (m, bad)
    assert any("before" in x for x in load_doc(sm.replace("from: Q1", "from: Q2").replace("to: Q2", "to: Q1"))[1])
    assert any("periods" in x for x in load_doc(sm.replace("periods: [Q1, Q2]", "periods: []"))[1])


def test_mermaid_blocks_validate():
    from strata.blocks import load_doc
    ok = """title: t
blocks:
  - diagram:
      nodes: [{id: a, shape: decision, tone: warn}, {id: b, shape: store}]
      edges: [[a, b, [x, y]], [b, a, "l1\\nl2"]]
  - statemachine:
      states: [a, b]
      initial_label: register
      transitions: [[a, b, [x, y]]]
"""
    assert load_doc(ok)[1] == []
    for old, new, msg in (("shape: decision", "shape: round", "shape must be"), ("tone: warn", "tone: red", "tone must be"),
                          ("[x, y]]", "[1]]", "label must be"), ("initial_label: register", "initial_label: [1]", "initial_label")):
        assert any(msg in x for x in load_doc(ok.replace(old, new, 1))[1]), (old, msg)


def test_details_validate():
    from strata.blocks import load_doc
    ok = "title: t\nblocks:\n  - diagram:\n      details_title: X\n      nodes: [{id: a, details: [[k, v `c`]]}]\n  - statemachine:\n      states: [{id: a, details: [[k, v]]}]\n"
    assert load_doc(ok)[1] == []
    for old, new in (("[[k, v `c`]]", "[k, v]"), ("[[k, v `c`]]", "[[k]]"), ("[[k, v]]", "[[k, 1]]"), ("details_title: X", "details_title: 1")):
        assert load_doc(ok.replace(old, new, 1))[1], (old, new)


def test_api_items_board_fields(env):
    base, p, _ = env
    SPEC = '{"goal":"g","acceptance":["a","b"],"verify":"v","scope":{"touch":["x"]}}'
    c = db.connect(p)
    c.execute("INSERT INTO item(project,kind,title,status,priority,spec) VALUES('a','task','nền','approved','high',?)", (SPEC,))  # id 3
    c.execute("INSERT INTO item(project,kind,title,status,spec) VALUES('a','task','phụ','approved',?)", (SPEC,))  # id 4
    c.execute("INSERT INTO item_dep VALUES(4,3)")
    c.execute("INSERT INTO c4_object(id,project,type,name) VALUES('o1','a','system','O1')")
    c.execute("INSERT INTO c4_link VALUES('a','o1','item',3)")
    c.commit()
    assert [x["id"] for x in J(env, "/api/items?project=a&ready=1")] == [3]  # 4 waits on 3
    assert [x["id"] for x in J(env, "/api/items?project=a&owner=nobody")] == []
    assert cli(p, "item", "claim", "3", "--as", "coder")[0] == 0
    assert [x["id"] for x in J(env, "/api/items?owner=coder")] == [3]
    d = J(env, "/api/items?id=3")[0]
    assert d["spec"]["acceptance"] == ["a", "b"] and d["claimed_at"]
    assert d["deps"] == {"needs": [], "blocks": [{"id": 4, "title": "phụ", "status": "approved"}]}
    assert d["links"]["c4"] == ["o1"] and "decisions" not in d["links"]
    assert d["history"][0]["to"] == "doing" and d["history"][0]["actor"] == "coder"
    assert J(env, "/api/items?id=4")[0]["deps"]["needs"][0]["id"] == 3
    assert "deps" not in J(env, "/api/items?project=a")[0]
    assert get(base, "/api/items?status=review")[0] == 200 and get(base, "/api/items?ready=1&status=bogus")[0] == 400


def test_server_has_no_write_routes():
    """The viewer is read-only: C4 is edited in the folder and imported with the CLI."""
    src = (ROOT / "strata/server.py").read_text()
    assert not any(m in src for m in ("do_POST", "do_PUT", "do_DELETE", "do_PATCH"))


def test_board_ui_filters_in_url():
    js = (ROOT / "viewer/app.js").read_text()
    assert "URLSearchParams" in js and "Sẵn sàng" not in js


def test_api_c4_layered_exposes_contracts_behavior(env):
    from strata import c4_layered
    b, p, _ = env
    c = db.connect(p); c4_layered.import_dir(c, ROOT / "tests/fixtures/c4_layered", "a"); c.close()
    m = J(env, "/api/c4?project=a")
    assert m["layered"] is True
    assert {x["id"]: x["detail"] for x in m["connections"] if x.get("detail")}["app_cmd"] == "relay_command.send"
    r = m["contracts"]["relay_command.send"]
    assert r["transport"] == "HTTPS POST /command/send" and r["body"]["errors"] == ["BUSY", "TIMEOUT"] and r["end"] == "src/relay.py::RelayHub.send"
    assert [t["id"] for t in m["behavior"]["relay"]["transitions"]] == ["t1"]
    assert next(o for o in m["objects"] if o["id"] == "relay")["owns"] == ["src/**"]
    assert any(s.get("link") == "app_cmd" for s in m["flows"][0]["steps"])


def test_viewer_script_calls_only_defined_functions():
    """Regression for #195: a prune once deleted the map renderer but the script still called it."""
    import re
    t = (ROOT / "viewer/index.html").read_text(encoding="utf-8")
    js = t[t.index("<script>\n"):t.rindex("</script>")]
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"(?m)(^|\s)//(\s.*)?$", "", js)
    js = re.sub(r"[,;]\s*([A-Za-z_$][\w$]*)\s*=(?!=)", lambda m: " let " + m.group(1) + "=", js)  # comma declarations
    js = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "''", js)
    js = re.sub(r"`[^`]*`", lambda m: " ".join(re.findall(r"\$\{(.*?)\}", m.group(0), flags=re.S)), js, flags=re.S)
    ident = r"[A-Za-z_$][\w$]*"
    defs = set(re.findall(rf"(?:function\*?|const|let|var|class)\s+({ident})", js))
    for m in re.finditer(r"(?:const|let|var)\s*[\[{]([^\]}=]*)[\]}]", js):
        defs |= set(re.findall(ident, m.group(1)))
    for m in re.finditer(rf"\(([^()]*)\)\s*=>|function\s*[\w$]*\s*\(([^()]*)\)|({ident})\s*=>|catch\s*\(([^)]*)\)", js):
        for g in m.groups():
            defs |= set(re.findall(ident, g or ""))
    calls = set(re.findall(rf"(?<![\w$.])({ident})\s*\(", js))
    ok = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "await", "new", "else", "do", "try",
          "async", "API", "prompt", "confirm", "alert", "String", "Number", "Object", "Array", "Math", "JSON", "Set", "Map", "Promise", "Boolean",
          "parseInt", "parseFloat", "fetch", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
          "requestAnimationFrame", "matchMedia", "isNaN", "encodeURIComponent", "decodeURIComponent", "Error", "Date",
          "URLSearchParams", "RegExp", "getComputedStyle", "isFinite", "structuredClone", "FormData", "Event",
          "CustomEvent", "ResizeObserver", "MutationObserver", "URL", "Blob", "AbortController", "dagre", "mermaid"}
    assert sorted(calls - defs - ok) == []


def test_viewer_status_class_is_whitelisted():
    src = (ROOT / "viewer/index.html").read_text()
    assert 'const stc=v=>SDOT[v]?v:"live"' in src
    assert "${c.status||" not in src and "c0.status||" not in src  # raw status must not reach class="..."
    assert src.count("stc(c.status)") == 1 and src.count("stc(c0.status)") == 1
