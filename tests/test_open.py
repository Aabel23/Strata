import io, json, os, subprocess, sys, urllib.request, pytest
import strata as _s  # noqa
from strata import db
import importlib.util, pathlib

spec = importlib.util.spec_from_file_location("strata_cli", pathlib.Path(__file__).resolve().parent.parent / "strata.py")
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)


@pytest.fixture
def c(dbp):
    c = db.init(str(dbp))
    return c


def add(c, pid, root):
    root.mkdir(parents=True, exist_ok=True); c.execute("INSERT INTO project(id,name,root) VALUES(?,?,?)", (pid, pid, str(root))); c.commit()


def test_resolution(c, tmp_path):
    add(c, "a", tmp_path / "a"); add(c, "b", tmp_path / "a/b"); (tmp_path / "a/sub").mkdir(); (tmp_path / "x").mkdir()
    (tmp_path / "ln").symlink_to(tmp_path / "a/b")
    f = lambda p: db.project_for_path(c, str(p))
    assert f(tmp_path / "a") == "a" and f(tmp_path / "a/sub") == "a" and f(tmp_path / "a/b") == "b"
    assert f(tmp_path / "ln") == "b" and f(tmp_path / "x") is None


def ok(*a, **k): return io.BytesIO(b'[{"id": "a"}]')


def test_open_retry_and_unknown(c, dbp, tmp_path, monkeypatch, capsys):
    add(c, "a", tmp_path / "a"); monkeypatch.setattr(cli.webbrowser, "open", lambda u: None); monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    args = ["open", str(tmp_path / "a"), "--db", str(dbp)]; n = []
    def flaky(*a, **k):
        n.append(1)
        if len(n) < 3: raise OSError
        return ok()
    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    assert cli.main(args) == 0 and len(n) == 3
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b'[{"id": "zzz"}]'))
    assert cli.main(args) == 1 and "doesn't know project a" in capsys.readouterr().out
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"<html>"))
    t = iter(range(0, 100, 3)); monkeypatch.setattr(cli.time, "monotonic", lambda: next(t))
    assert cli.main(args) == 1 and "isn't running" in capsys.readouterr().out


def install(home, *a):
    r = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), *a], capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    return r.returncode, r.stdout


ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_install_conflicts(tmp_path):
    h = tmp_path / "h"; b = h / ".local/bin"; b.mkdir(parents=True); link = b / "strata"
    assert install(h)[0] == 0 and link.resolve() == ROOT / "strata.py"
    rc, out = install(h); assert rc == 0 and "Already installed" in out
    link.unlink(); link.write_text("mine")
    rc, out = install(h); assert rc == 1 and "--force" in out and link.read_text() == "mine"
    rc, out = install(h, "--force"); assert rc == 0 and "replacing" in out and link.is_symlink()
    link.unlink(); link.symlink_to("/etc/hostname")
    rc, out = install(h); assert rc == 1 and os.readlink(link) == "/etc/hostname"
    rc, out = install(h, "--force"); assert rc == 0 and "replacing" in out and link.resolve() == ROOT / "strata.py"


def test_open(c, dbp, tmp_path, monkeypatch, capsys):
    add(c, "a", tmp_path / "a"); opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    args = ["open", str(tmp_path / "a"), "--db", str(dbp)]
    assert cli.main(["open", str(tmp_path), "--db", str(dbp)]) == 1 and "strata init" in capsys.readouterr().out
    def down(*a, **k): raise OSError
    monkeypatch.setattr(urllib.request, "urlopen", down)
    assert cli.main(args) == 1 and "viewer isn't running" in capsys.readouterr().out
    monkeypatch.setattr(urllib.request, "urlopen", ok)
    assert cli.main(args) == 0 and opened == ["http://127.0.0.1:8740/#/p/a"]
    assert cli.main(args + ["--port", "9"]) == 0 and opened[-1] == "http://127.0.0.1:9/#/p/a"
