import json
import pytest
from strata import c4, context, db, service
from test_c4 import EX

SPEC = {"goal": "G", "acceptance": ["A1"], "verify": "pytest -q", "scope": {"touch": ["a/b.py", "c.py"]}, "note": "see decision 2"}


@pytest.fixture
def env(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# X\n\n## Luật cứng\n\n1. RULE-ONE\n2. RULE-TWO\n\n## Khác\nOTHER\n", encoding="utf-8")
    c = db.init(str(tmp_path / "t.db")); db.add_project(c, "p", "P", root=str(tmp_path))
    c4.import_yaml(c, str(EX), "p", False)
    d1 = service.add_decision(c, "main", "p", "D one", "ctx", "X" * 300, "cons", "rej")
    d2 = service.add_decision(c, "main", "p", "D two", "ctx", "second", "cons", "rej")
    dep = service.add_item(c, "main", "p", "task", "Dep", spec=SPEC)
    t = service.add_item(c, "main", "p", "task", "Main task", spec=SPEC)
    service.dep(c, "main", t, dep)
    c.execute("INSERT INTO c4_link(project,object_id,ref_kind,ref_id) VALUES('p','relay','item',?)", (t,))
    c.execute("INSERT INTO c4_link(project,object_id,ref_kind,ref_id) VALUES('p','relay','decision',?)", (d1,)); c.commit()
    return c, t, tmp_path


def test_includes_everything(env, capsys):
    c, t, _ = env; out = context.build(c, t)
    for s in ("Main task", "pytest -q", "A1", "depends_on #", "RULE-TWO", "#1 D one — " + "X" * 160, "#2 D two — second", "## C4 relay", "a/b.py"): assert s in out
    assert "OTHER" not in out and "X" * 161 not in out and capsys.readouterr().err == ""


def test_missing_claude_md_ok(env, capsys):
    c, t, root = env; (root / "CLAUDE.md").unlink()
    out = context.build(c, t)
    assert "Main task" in out and "Luật cứng" not in out and "missing" in capsys.readouterr().err


def test_budget_cut_priority(env, capsys):
    c, t, _ = env; full = context.build(c, t); capsys.readouterr()
    for b in (len(full) - 1, 700, 300):
        out = context.build(c, t, b); err = capsys.readouterr().err
        assert len(out) <= b and "Main task" in out and ("cut" in err or "truncated" in err)
    out = context.build(c, t, 700); err = capsys.readouterr().err
    assert len(out) <= 700 and "Main task" in out and "RULE-TWO" in out and "## Paths" not in out and "cut" in err
    assert ("## Decisions" in out) == ("cut decisions" not in err)
