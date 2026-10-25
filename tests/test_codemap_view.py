import threading, urllib.error, urllib.request
import pytest
from strata import db, server


@pytest.fixture
def base(tmp_path):
    p = str(tmp_path / "t.db"); db.init(p).close()
    srv = server.make_server(p, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown(); srv.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url) as r: return r.status, r.headers["Content-Type"]
    except urllib.error.HTTPError as e: return e.code, None


def test_codemap_static(base):
    assert get(base + "/codemap/") == (200, "text/html; charset=utf-8")
    assert get(base + "/codemap/js/main.js") == (200, "application/javascript; charset=utf-8")
    assert get(base + "/codemap/vendor/graphology.mjs") == (200, "text/javascript; charset=utf-8")
    assert get(base + "/codemap/nope.js")[0] == 404


@pytest.mark.parametrize("path", ["/codemap/../strata.db", "/codemap/%2e%2e/app.js", "/codemap/..%2fapp.js", "/codemap/js/..%2f..%2f..%2fapp.js"])
def test_codemap_traversal(base, path):
    assert get(base + path)[0] in (400, 404)
