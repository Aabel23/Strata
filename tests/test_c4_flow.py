import pathlib
import pytest
from strata import c4
from test_c4 import EX, run

ROOT = pathlib.Path(".")
OBJS = [{"id": "a", "type": "system", "description": "x", "name": "n"}, {"id": "b", "type": "system", "description": "x", "name": "n"},
        {"id": "c", "type": "system", "description": "x", "name": "n"}, {"id": "b1", "type": "app", "parent": "b", "description": "x", "name": "n"}]
CONNS = [{"id": "ab", "from": "a", "to": "b", "technology": "t"}, {"id": "bc", "from": "b", "to": "c", "technology": "t"},
         {"id": "b1c", "from": "b1", "to": "c", "technology": "t"}]
IFS = [{"id": "i1", "object": "b"}]


def chk(*steps):
    errs, warns, *_ = c4.check({"objects": OBJS, "connections": CONNS, "interfaces": IFS, "flows": [{"id": "f", "steps": list(steps)}]}, ROOT)
    return errs, [w for w in warns if "flow" in w]


def test_valid_forms_and_continuity():
    assert chk({"connection": "ab"}, {"at": "b", "interface": "i1"}, {"connection": "bc", "payload": "x"}) == ([], [])
    assert chk({"from": "a", "to": "b"}, {"connection": "b1c"}) == ([], [])              # legacy form; descendant start
    assert chk({"connection": "ab"}, {"connection": "ab", "reverse": True}) == ([], [])  # response goes back b → a
    errs, warns = chk({"connection": "ab"}, {"connection": "ab"})
    assert errs == [] and len(warns) == 1 and "đứt mạch" in warns[0]


@pytest.mark.parametrize("step,msg", [
    ({"connection": "ab", "at": "a"}, "đúng một"), ({}, "đúng một"), ({"at": "zz"}, "không tồn tại"),
    ({"connection": "zz"}, "không tồn tại"), ({"at": "a", "reverse": True}, "reverse"),
    ({"at": "a", "interface": "nope"}, "interface"), ({"from": "a", "to": "c"}, "không khớp"),
])
def test_step_errors(step, msg):
    errs, _ = chk(step)
    assert len(errs) == 1 and msg in errs[0]


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"
    run(p, "import-yaml", str(EX), "--project", "p")
    return p


def test_example_is_clean():
    errs, warns, *_ = c4.check(*c4.load(EX))
    assert errs == [] and not [w for w in warns if "đứt mạch" in w]


def test_flow_cli(dbp):
    code, out = run(dbp, "c4", "flow", "--project", "p")
    assert code == 0 and "menu_refresh" in out and "bước" in out
    code, out = run(dbp, "c4", "flow", "--project", "p", "--id", "menu_refresh")
    lines = out.splitlines()
    assert code == 0 and lines[0].startswith("# menu_refresh")
    assert "7. cloud.CloudClient.post/_send → transport.http.Handler.do_POST [network]" in out
    assert any(l.startswith("8. @ transport.http.Handler.do_POST") for l in lines)
    assert "[call ↩]" in out and "| payload: " in out and "(sec_open)" in out
    assert run(dbp, "c4", "flow", "--project", "p", "--id", "zz")[0] == 1


def test_overview_has_interfaces_connections_flows(dbp):
    code, out = run(dbp, "c4", "context", "--project", "p")
    assert code == 0 and "· sec_open: open_request(" in out and "- menu_refresh (68 bước)" in out
    assert "- transport→security [call] Mở/đóng phong bì (sec_open)" in out
    code, small = run(dbp, "c4", "context", "--project", "p", "--max-tokens", "1200")
    assert "... (cắt " in small and len(small) // 4 <= 1300


def test_validate_bad_yaml_reports_line(tmp_path, capsys):
    f = tmp_path / "m.yaml"; f.write_text("objects:\n  - {id: a, description: x: y}\n", encoding="utf-8")
    assert c4.validate_file(f) == 1
    assert "dòng 2" in capsys.readouterr().out


def test_unquoted_comma_warns_unknown_key(tmp_path):
    m = {"objects": [{"id": "a", "type": "actor", "description": "x", "y": None}]}
    errs, warns, *_ = c4.check(m, tmp_path)
    assert any("key lạ ['y']" in w for w in warns)
