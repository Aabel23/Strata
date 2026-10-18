import pytest
from strata import c4, db
from test_c4 import EX, run


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"
    run(p, "import-yaml", str(EX), "--project", "p")
    run(p, "item", "add", "--project", "p", "--kind", "issue", "--title", "Lỗi relay")
    run(p, "c4", "link", "--project", "p", "--object", "relay", "--item", "1")
    return p


def ctx(dbp, *a): return run(dbp, "c4", "context", "--project", "p", *a)


def test_object_context_sections(dbp):
    code, out = ctx(dbp, "--object", "server")
    assert code == 0
    assert out.startswith("# server [app]") and "Cha: Nền tảng project1" in out
    assert "- transport [component]" in out and "- relay [component]" in out
    assert "→" in out and "Flow:" in out                      # connections and flows of the subtree
    code, out = ctx(dbp, "--object", "transport")
    assert "Flutter" in out or "flutter" in out.lower()       # connection from the sibling-level app
    assert "- relay" not in out.split("Con:")[1].split("Connection")[0]   # no children
    assert "issue #1 [open] Lỗi relay" in ctx(dbp, "--object", "relay")[1]


def test_merged_connections(dbp):
    c = db.connect(dbp)
    c.execute("INSERT INTO c4_connection(id,project,from_id,to_id) VALUES('x1','p','flutter','security')"); c.commit()
    out = c4.context_text(c, "p", "server")
    assert "- Flutter app → Cloud server: 2 kết nối" in out or "2 kết nối" in out


def test_overview(dbp):
    code, out = ctx(dbp, )
    assert code == 0 and "1 issue mở" in out and "  - flutter [app]" in out and "- relay [component]" in out and "— 1 issue mở" in out


def test_truncation_order(dbp):
    c = db.connect(dbp)
    full = c4.context_text(c, "p", "server", 100000)
    assert "cắt" not in full
    out = c4.context_text(c, "p", "server", len(full) // 4 - 5)
    assert "... (cắt: flow)" in out and "Cha:" in out and "Con:" in out
    tiny = c4.context_text(c, "p", "server", 20)
    assert "... (cắt: flow)" in tiny and "... (cắt: con trực tiếp)" in tiny and "Cha:" in tiny and tiny.startswith("# server")


def test_unknown(dbp):
    assert ctx(dbp, "--object", "zz")[0] == 1 and ctx(dbp, "--object", "zz")[1].startswith("ERROR")
    assert run(dbp, "c4", "context", "--project", "zz")[0] == 1
