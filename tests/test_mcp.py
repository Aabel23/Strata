import json, pathlib, subprocess, sys
import pytest
from strata import db

ROOT = pathlib.Path(__file__).parent.parent


def run(tmp_path, role, msgs, db_=None):
    p = db_ or str(tmp_path / "m.db")
    c = db.init(p); db.add_project(c, "p", "P") if not c.execute("SELECT 1 FROM project").fetchone() else None; c.close()
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), "mcp", "--role", role, "--db", p], input="\n".join(json.dumps(m) if isinstance(m, dict) else m for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=30)
    return r, [json.loads(l) for l in r.stdout.splitlines()]


def call(i, name, **a): return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": a}}


def test_handshake_list_ping_unknown(tmp_path):
    r, out = run(tmp_path, "main", [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"}, "not json"])
    assert r.returncode == 0 and len(out) == 5  # the notification got no reply
    assert out[0]["result"]["protocolVersion"] == "2025-03-26" and "tools" in out[0]["result"]["capabilities"] and out[0]["result"]["serverInfo"]["name"]
    assert out[1]["result"] == {}
    tools = {t["name"]: t for t in out[2]["result"]["tools"]}
    assert set(tools) == {"add_item", "set_item", "add_decision", "set_decision_status", "search"}
    assert all("role" not in t["inputSchema"]["properties"] and t["inputSchema"]["type"] == "object" for t in tools.values())
    assert out[3]["error"]["code"] == -32601 and out[4]["error"]["code"] == -32700


def test_tools_and_role_fixed(tmp_path):
    p = str(tmp_path / "m.db")
    r, out = run(tmp_path, "coder", [
        call(1, "add_item", project="p", kind="issue", title="bug zork", role="main"),  # role arg ignored
        call(2, "add_item", project="p", kind="task", title="nope"),
        call(3, "add_decision", project="p", title="T", context="c", decision="d", consequences="q", rejected="r"),
        call(4, "add_decision", project="p", title="T", context="c", decision="d", consequences="q", rejected=""),
        call(5, "set_decision_status", id=1, status="accepted"),
        call(6, "search", q="zork"),
        call(7, "set_item", id=1, status="done")], p)
    assert r.returncode == 0 and r.stdout.count("\n") == 7  # server survived every error
    flags = [o["result"]["isError"] for o in out]
    assert flags == [False, True, False, True, True, False, True]
    assert json.loads(out[5]["result"]["content"][0]["text"])[0]["title"] == "bug zork"
    c = db.connect(p)
    assert c.execute("SELECT created_by FROM item WHERE id=1").fetchone()[0] == "coder"
    assert c.execute("SELECT status FROM decision WHERE id=1").fetchone()[0] == "proposed"
    assert {r[0] for r in c.execute("SELECT actor_role FROM audit WHERE tool IN ('item.add','decision.add')")} == {"coder"}


def test_main_decision_and_bad_role(tmp_path):
    r, out = run(tmp_path, "main", [call(1, "add_decision", project="p", title="T", context="c", decision="d", consequences="q", rejected="r"),
                                    call(2, "set_decision_status", id=1, status="superseded")])
    assert [o["result"]["isError"] for o in out] == [False, False]
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), "mcp", "--role", "root", "--db", str(tmp_path / "x.db")], input="", capture_output=True, text=True)
    assert r.returncode != 0 and r.stdout == ""


def test_malformed_input_never_crashes(tmp_path):
    bad = [call(1, "add_decision", project="p", title="T", context="c", decision="d", consequences="q", rejected=5),
           {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": [1]},
           {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": [1]}},
           {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": ["x"]}},
           '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"set_item","arguments":{"id":1e23}}}',
           '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"search","arguments":{"q":"a","limit":1e400}}}',
           call(7, "set_item", id=True), call(8, "set_item", id=10**30), call(9, "search", q=["a"]),
           '[{"jsonrpc":"2.0","id":10,"method":"ping"}]', "[" * 100000,
           {"jsonrpc": "2.0", "id": 11, "method": "ping"}]
    r, out = run(tmp_path, "coder", bad)
    assert r.returncode == 0 and len(out) == len(bad)
    assert [o["error"]["code"] for o in out[1:4]] == [-32602] * 3
    assert all(o["result"]["isError"] for o in out[0:1] + out[4:9])
    assert out[9]["error"]["code"] == -32600 and out[10]["error"]["code"] == -32700 and out[11]["result"] == {}


def test_missing_project_clean_error(tmp_path):
    r, out = run(tmp_path, "main", [call(1, "add_item", project="zz", kind="task", title="t")])
    res = out[0]["result"]
    assert res["isError"] and res["content"][0]["text"] == "error: no project zz" and "Traceback" not in r.stderr
