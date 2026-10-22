import os, pathlib, shutil
import pytest
from strata import c4_layered as L, symbols as S
from test_c4_layered import folder  # noqa: F401

SRC = 'class A:\n    """Doc A.\n\n    more"""\n    def m(self, x: int) -> str:\n        return ""\n    def _p(self): pass\n\n@dec\nasync def f(a, *, b=1):\n    def inner(): pass\n'


@pytest.fixture
def idx(tmp_path):
    root = tmp_path / "proj"; (root / "pkg").mkdir(parents=True); (root / "venv").mkdir(); (root / "venv/x.py").write_text("def v(): pass\n")
    (root / "pkg/a.py").write_text(SRC); (root / "bad.py").write_text("def (:\n")
    return root, S.connect(tmp_path / "t.symbols.db")


def test_index_ls_show(idx):
    root, c = idx
    assert S.index(c, "p", root) == (2, 0, 0) and S.index(c, "p", root) == (0, 2, 0)   # venv skipped, bad.py kept without symbols
    assert [S.line(r) for r in S.ls(c, "p", "pkg/a.py")] == ["class A -- Doc A.", "def A.m(self, x: int) -> str", "def A._p(self)", "async def f(a, *, b=1)"]
    assert [r["name"] for r in S.ls(c, "p", "pkg", public=True)] == ["A", "m", "f"] and not S.find(c, "p", "inner") and S.find(c, "p", "A.m")[0]["start_line"] == 5
    assert S.ls(c, "p", "pkg/a.py")[3]["start_line"] == 9    # decorator line counts
    t, ok = S.show(c, "p", root, "pkg/a.py::A.m"); assert ok and t.endswith("def m(self, x: int) -> str:\n        return \"\"")
    assert S.show(c, "p", root, "pkg/a.py::A.m", ctx=1)[0].count("\n") == 4
    assert S.show(c, "p", root, "pkg/a.py::A.m", sig_only=True)[0].endswith("def A.m(self, x: int) -> str")
    t, ok = S.show(c, "p", root, "pkg/a.py::B.m"); assert not ok and "ứng viên: pkg/a.py::A.m" in t


def test_reindex_only_changed_and_stale_show(idx):
    root, c = idx; S.index(c, "p", root)
    f = root / "pkg/a.py"; f.write_text("\n\n" + SRC)           # lines shift; show re-checks disk before slicing
    assert S.show(c, "p", root, "pkg/a.py::A.m")[0].startswith("# pkg/a.py::A.m dòng 7-8")
    (root / "bad.py").unlink(); assert S.index(c, "p", root) == (0, 1, 1)
    long = root / "big.py"; long.write_text("def g():\n" + "    x = 1\n" * 250); S.index(c, "p", root)
    t, _ = S.show(c, "p", root, "big.py::g"); assert t.endswith("cắt ở 200 dòng") and t.count("\n") == 201


def test_containment(idx, tmp_path):
    root, c = idx
    (tmp_path / "secret.py").write_text("def s(): pass\n"); os.symlink(tmp_path / "secret.py", root / "link.py")
    S.index(c, "p", root); assert not S.find(c, "p", "link.py")                  # symlink out of root not indexed
    for sid in ("../secret.py::s", str(tmp_path / "secret.py") + "::s", "link.py::s"):
        t, ok = S.show(c, "p", root, sid); assert not ok and "ngoài root" in t
    assert S.inside(root, "pkg/../pkg/a.py") and not S.inside(root, "/etc/passwd")


def test_validate_uses_index_and_rejects_outside(folder):
    m, _ = L.load(folder); root = (folder / "..").resolve()
    c = S.connect(folder.parent / "x.symbols.db"); S.index(c, "p", root)
    base = L.check(m, folder)[1]
    assert L.check(m, folder, (c, "p"))[1] == base
    (root / "src/app.py").write_text("def helper(): pass\n")      # index now stale (mtime/size) -> falls back to ast, still correct
    assert any("App.ask" in w for w in map(L.fmt, L.check(m, folder, (c, "p"))[1]))
    assert S.resolves(c, "p", root, "src/relay.py::RelayHub.send") is True
    (root / "../escape.py").write_text("def e(): pass\n")
    assert L.resolve("../escape.py::e", root, {}) == "../escape.py: ngoài root" and L.resolve("/etc/passwd::x", root, {}).endswith("ngoài root")


def test_cli(tmp_path, capsys, monkeypatch):
    import strata as _s, importlib.util
    spec = importlib.util.spec_from_file_location("strata_cli", pathlib.Path(__file__).parent.parent / "strata.py"); cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    proj = tmp_path / "pr"; proj.mkdir(); (proj / "m.py").write_text(SRC); d = str(tmp_path / "s.db")
    r = lambda *a: cli.main([*a, "--db", d])
    assert r("project", "add", "p", "--name", "P", "--root", str(proj)) == 0 and r("sym", "index", "--project", "p") == 0
    assert (tmp_path / "s.symbols.db").exists()
    capsys.readouterr(); assert r("sym", "ls", "m.py", "--project", "p", "--public") == 0 and "def A.m" in capsys.readouterr().out
    assert r("sym", "show", "m.py::f", "--project", "p", "--sig-only") == 0 and r("sym", "find", "A", "--project", "p") == 0
    assert r("sym", "show", "../m.py::f", "--project", "p") == 1 and "ngoài root" in capsys.readouterr().out


def test_alias_like_and_non_utf8(idx, monkeypatch):
    root, c = idx
    (root / "pkg/a_b.py").write_text("def q(): pass\n"); (root / "pkg/axb.py").write_text("def r(): pass\n"); (root / "pkg/lat.py").write_bytes("def z(): 'é'\n".encode("latin-1"))
    assert S.refresh(c, "p", root, "pkg/../pkg/a.py") and S.refresh(c, "p", root, "pkg/a.py")
    assert c.execute("SELECT count(*) FROM file WHERE path LIKE '%a.py'").fetchone()[0] == 1 and not S.refresh(c, "p", root, "../x.py")
    assert S.show(c, "p", root, "pkg/../pkg/a.py::A.m")[1] and S.resolves(c, "p", root, "pkg/../pkg/a.py::A.m") is True
    S.index(c, "p", root)
    assert [r["name"] for r in S.find(c, "p", "a_b")] == ["q"] and [r["name"] for r in S.ls(c, "p", "pkg/a_b.py")] == ["q"] and not S.find(c, "p", "%")
    assert S.show(c, "p", root, "pkg/lat.py::z")[1] is False       # latin-1 file: no symbols, no raise
    def boom(*a, **k): raise UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "x")   # file turns non-UTF-8 between refresh and read
    monkeypatch.setattr(pathlib.Path, "read_text", boom); t, ok = S.show(c, "p", root, "pkg/a.py::A.m"); assert not ok and "UTF-8" in t
