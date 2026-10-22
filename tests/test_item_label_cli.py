import importlib.util, pathlib
from strata import db

ROOT = pathlib.Path(__file__).parent.parent
sp = importlib.util.spec_from_file_location("cli", ROOT / "strata.py"); cli = importlib.util.module_from_spec(sp); sp.loader.exec_module(cli)


def test_issue_alias_and_label_filter(tmp_path, capsys):
    d = str(tmp_path / "t.db"); db.add_project(db.init(d), "p", "P")
    run = lambda *x: (cli.main([*x, "--db", d]), capsys.readouterr().out)
    assert run("item", "add", "--project", "p", "--kind", "issue", "--title", "A")[0] == 0
    assert run("item", "add", "--project", "p", "--kind", "task", "--label", "issue", "--title", "B")[0] == 0
    run("item", "add", "--project", "p", "--kind", "task", "--title", "C")
    by_label = run("item", "list", "--project", "p", "--label", "issue")[1]
    assert by_label == run("item", "list", "--project", "p", "--kind", "issue")[1]
    assert by_label.count("\n") == 2 and "[issue] A" in by_label and "[issue] B" in by_label and "C" not in by_label
    assert "[issue] A" in run("item", "show", "1")[1]
    assert run("item", "reject", "1", "--note", "n")[0] == 0
