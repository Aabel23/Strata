"""Files tab: strata/files.py path rules and the /api/files, /api/file routes (guards, then one real round trip)."""
import json, os, threading, urllib.error, urllib.request
import pytest
from strata import db, files, server


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "proj"; (r / "src").mkdir(parents=True); (r / ".git").mkdir()
    (r / "src" / "a.py").write_text("x = 1\n"); (r / ".env").write_text("K=1\n"); (r / ".git" / "config").write_text("[core]\n")
    (r / "bin.dat").write_bytes(b"\0\1\2")
    (tmp_path / "outside.txt").write_text("secret")
    os.symlink(tmp_path / "outside.txt", r / "leak")
    return r


def test_listing_hides_git_and_sorts_folders_first(root):
    r = files.listing(str(root))
    assert [(e["name"], e["dir"]) for e in r["entries"]] == [("src", True), (".env", False), ("bin.dat", False), ("leak", False)]
    assert files.listing(str(root), "src")["entries"] == [{"name": "a.py", "dir": False}]


@pytest.mark.parametrize("rel", ["../outside.txt", "src/../../outside.txt", ".git/config", "leak", "a\0b", "./src"])
def test_paths_outside_the_root_are_refused(root, rel):
    with pytest.raises(files.FileError): files.read(str(root), rel)
    with pytest.raises(files.FileError): files.write(str(root), rel, "x")


def test_read_write_conflict_and_binary(root):
    r = files.read(str(root), "src/a.py")
    assert r["text"] == "x = 1\n" and "skipped" in files.read(str(root), "bin.dat")
    os.chmod(root / "src" / "a.py", 0o755)
    w = files.write(str(root), "src/a.py", "x = 2\n", r["mtime"])
    assert (root / "src" / "a.py").read_text() == "x = 2\n" and (root / "src" / "a.py").stat().st_mode & 0o777 == 0o755
    with pytest.raises(files.Conflict): files.write(str(root), "src/a.py", "x = 3\n", r["mtime"])  # stale stamp
    assert files.write(str(root), "src/a.py", "x = 3\n", w["mtime"])["size"] == 6
    assert [p.name for p in (root / "src").iterdir()] == ["a.py"]  # no temp file left behind
    with pytest.raises(FileNotFoundError): files.write(str(root), "src/new.py", "")


def test_create_rename_delete(root):
    files.create(str(root), "pkg", folder=True); files.create(str(root), "pkg/b.py")
    with pytest.raises(files.Conflict): files.create(str(root), "pkg/b.py")
    assert files.rename(str(root), "pkg/b.py", "pkg/c.py")["path"] == "pkg/c.py"
    with pytest.raises(files.Conflict): files.rename(str(root), "src/a.py", "pkg/c.py")
    with pytest.raises(files.Conflict): files.delete(str(root), "pkg")  # not empty
    with pytest.raises(files.FileError): files.delete(str(root), "", recursive=True)  # never the root
    files.delete(str(root), "pkg", recursive=True)
    assert not (root / "pkg").exists()


@pytest.fixture
def srv(tmp_path, root):
    p = tmp_path / "t.db"; c = db.init(str(p)); db.add_project(c, "a", "A", root=str(root)); db.add_project(c, "bare", "Bare"); c.close()
    made = []

    def make(**kw):
        s = server.make_server(p, None, 0, **kw)
        threading.Thread(target=s.serve_forever, daemon=True).start(); made.append(s)
        return f"127.0.0.1:{s.server_address[1]}"
    yield make
    for s in made: s.shutdown(); s.server_close()


def call(hp, path, body=None, **hdr):
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: session = json.load(r)
    h = {"X-Strata-Token": session["token"], **({"X-Strata-Edit": "1", "Content-Type": "application/json"} if body is not None else {}), **hdr}
    req = urllib.request.Request("http://" + hp + path, json.dumps(body).encode() if body is not None else None, h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_file_routes_round_trip(srv, root):
    hp = srv()
    st, r = call(hp, "/api/files?project=a")
    assert st == 200 and r["entries"][0] == {"name": "src", "dir": True}
    st, r = call(hp, "/api/file?project=a&path=src/a.py")
    assert st == 200 and r["text"] == "x = 1\n"
    big = "é" * 200000  # larger than the 64 KB limit of the other POST routes
    st, w = call(hp, "/api/file", {"op": "write", "project": "a", "path": "src/a.py", "text": big, "mtime": r["mtime"]})
    assert st == 200 and (root / "src" / "a.py").read_text() == big
    assert call(hp, "/api/file", {"op": "write", "project": "a", "path": "src/a.py", "text": "x", "mtime": r["mtime"]})[0] == 409
    assert call(hp, "/api/file", {"op": "create", "project": "a", "path": "src/n.py"})[0] == 200
    assert call(hp, "/api/file", {"op": "rename", "project": "a", "path": "src/n.py", "to": "src/m.py"})[1]["path"] == "src/m.py"
    assert call(hp, "/api/file", {"op": "mkdir", "project": "a", "path": "d"})[1]["dir"] is True
    assert call(hp, "/api/file", {"op": "delete", "project": "a", "path": "src", "recursive": True})[0] == 200 and not (root / "src").exists()


def test_file_routes_guards(srv):
    hp = srv()
    assert call(hp, "/api/files?project=a", **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, "/api/file?project=a&path=.env", **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, "/api/file", {"op": "create", "project": "a", "path": "x"}, **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, "/api/file", {"op": "create", "project": "a", "path": "x"}, Origin="http://evil.test")[0] == 403
    assert call(hp, "/api/file?project=a&path=../outside.txt")[0] == 400
    assert call(hp, "/api/file?project=a&path=leak")[0] == 400
    assert call(hp, "/api/file?project=a&path=.git/config")[0] == 400
    assert call(hp, "/api/file?project=a&path=nope.txt")[0] == 404
    assert call(hp, "/api/files?project=bare")[0] == 404 and call(hp, "/api/files?project=zz")[0] == 404
    assert call(hp, "/api/file", {"op": "write", "project": "a", "path": "../outside.txt", "text": "x"})[0] == 400
    assert call(hp, "/api/file", {"op": "chmod", "project": "a", "path": "src/a.py"})[0] == 400
    assert call(hp, "/api/file", {"op": "delete", "project": "a", "path": ""})[0] == 400
    off = srv(allow_edit=False)
    assert call(off, "/api/files?project=a")[0] == 403 and call(off, "/api/file?project=a&path=src/a.py")[0] == 403
    assert call(off, "/api/file", {"op": "create", "project": "a", "path": "x"})[0] == 403
