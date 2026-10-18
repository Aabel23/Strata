import json, pathlib, shutil, subprocess, sys, threading, urllib.error, urllib.request
import pytest
from strata import db, server

ROOT = pathlib.Path(__file__).resolve().parent.parent
XSS = "<script>alert(1)</script>"


@pytest.fixture
def env(tmp_path):
    p = tmp_path / "t.db"
    c = db.init(p)
    db.put_page(c, "p", "s", "Trang", "note", [{"type": "md", "text": XSS}])
    for i, (st, pr) in enumerate([("open", "p"), ("done", "p"), ("open", "q")]):
        c.execute("INSERT INTO item(project,kind,title,status) VALUES(?, 'task', ?, ?)", (pr, f"t{i}", st))
    c.commit()
    s = server.make_server(p, None, 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", c
    s.shutdown(); s.server_close()


def get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""


def test_routes(env):
    b, _ = env
    for ok in ("/pages", "/pages?project=p", "/page/p/s", "/page.js", "/page.css", "/vendor/mermaid.min.js", "/api/pages", "/api/page/p/s"):
        assert get(b, ok)[0] == 200, ok
    for no in ("/page/p/zz", "/api/page/p/zz", "/api/page/p/zz/version", "/vendor/nope.js", "/page/p"):
        assert get(b, no)[0] == 404, no
    assert [x["slug"] for x in json.loads(get(b, "/api/pages?project=p")[1])] == ["s"]
    assert json.loads(get(b, "/api/pages?project=zz")[1]) == []


def test_vendor_traversal(env):
    b, _ = env
    for bad in ("/vendor/../index.html", "/vendor/%2e%2e/index.html", "/vendor/..%2findex.html", "/vendor/%2e%2e%2fpage.js"):
        assert get(b, bad)[0] == 404, bad


def test_api_returns_raw_text_as_json(env):
    b, _ = env
    assert json.loads(get(b, "/api/page/p/s")[1])["blocks"][0]["text"] == XSS


def test_page_js_never_injects_html():
    js = (ROOT / "viewer/page.js").read_text()
    assert js.count("innerHTML") == 2  # one assignment (mermaid SVG) + the comment line
    assert not any(w in js for w in ("insertAdjacentHTML", "document.write", "eval(", "outerHTML"))


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_md_escapes_script(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(r"""
const fs=require('fs'), vm=require('vm');
function mk(tag){const e={tag,children:[],className:'',
  set textContent(v){this.children=[{text:String(v)}]}, append(...xs){xs.forEach(x=>this.children.push(typeof x==='string'?{text:x}:x))},
  set innerHTML(v){throw new Error('innerHTML')}};return e}
const ctx={document:{createElement:mk,getElementById:()=>mk('main'),documentElement:{dataset:{}}},localStorage:{getItem:()=>null},
  location:{pathname:'/pages',search:''},fetch:()=>new Promise(()=>{}),setInterval(){},matchMedia:()=>({matches:false}),URLSearchParams,encodeURIComponent,decodeURIComponent};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+';this.md=md',ctx);
const tree=ctx.md(process.argv[3]);
const tags=[],texts=[];(function w(n){if(n.tag)tags.push(n.tag);(n.children||[]).forEach(c=>c.text!==undefined?texts.push(c.text):w(c))})(tree);
console.log(JSON.stringify({tags,texts}));
""")
    src = "# Head\n\n" + XSS + " **b** [x](javascript:alert(1)) [ok](https://a.b)\n\n- `<img onerror=1>`\n"
    out = json.loads(subprocess.run(["node", str(js), str(ROOT / "viewer/page.js"), src], capture_output=True, text=True, check=True).stdout)
    assert "script" not in out["tags"] and "img" not in out["tags"]
    assert any(XSS in t for t in out["texts"]) and "<img onerror=1>" in out["texts"]
    assert out["tags"].count("a") == 1  # javascript: link is not an anchor
    assert {"h2", "p", "strong", "ul", "li", "code"} <= set(out["tags"])


def q(b, qs):
    return get(b, "/api/query?" + qs)


def test_query_filtering(env):
    b, _ = env
    rows = lambda qs: json.loads(q(b, qs)[1])
    assert len(rows("src=item")) == 3
    assert [r["title"] for r in rows("src=item&project=p&status=open")] == ["t0"]
    assert len(rows("src=item&limit=1")) == 1
    assert rows("src=decision") == []


@pytest.mark.parametrize("qs", ["src=audit", "", "src=item&body=x", "src=item&nope=1", "src=item&limit=0", "src=item&limit=x",
                                "src=item&limit=999", "src=item&status=", "src=decision&kind=task", "src=item&1=1)%20OR%20(1=1"])
def test_query_400(env, qs):
    assert q(env[0], qs)[0] == 400


def test_query_quote_safety(env):
    b, c = env
    for evil in ("' OR 1=1 --", "x'; DROP TABLE item; --", '" OR ""="'):
        st, body = q(b, "src=item&status=" + urllib.request.quote(evil))
        assert st == 200 and json.loads(body) == []
    assert c.execute("SELECT count(*) FROM item").fetchone()[0] == 3


def test_version_changes_after_put(env):
    b, c = env
    v = lambda: json.loads(get(b, "/api/page/p/s/version")[1])["version"]
    v0 = v()
    assert v() == v0
    db.put_page(c, "p", "s", "Trang", "note", [{"type": "md", "text": "mới"}])
    v1 = v()
    assert v1 != v0
    c.execute("INSERT INTO item(project,kind,title,status) VALUES('p','task','x','open')"); c.commit()
    assert v() != v1  # any DB write bumps data_version, so live query blocks refresh too


def raw(b, path, host=None):
    import http.client
    h = http.client.HTTPConnection(b.split("//")[1])
    h.putrequest("GET", path, skip_host=True)
    h.putheader("Host", host or b.split("//")[1]); h.endheaders()
    return h.getresponse().status


def test_host_header_guard(env):
    b, _ = env
    assert raw(b, "/pages") == 200 and raw(b, "/pages", "localhost:" + b.rsplit(":")[-1]) == 200
    assert raw(b, "/pages", "evil.com") == 403 and raw(b, "/api/pages", "127.0.0.1:1") == 403


def test_nul_in_paths_404(env):
    b, _ = env
    assert raw(b, "/vendor/%00x") == 404 and raw(b, "/code/%00x") == 404


def test_page_js_rejects_backslash_links():
    assert r"\/(?![\/\\])" in (ROOT / "viewer/page.js").read_text()
