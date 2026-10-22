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


MAIN_TOOLS = ["list_projects", "list_items", "get_item", "get_doc", "c4_context", "c4_flow", "audit", "search", "task_context", "add_item", "edit_item",
              "item_claim", "item_submit", "item_approve", "item_reject", "item_release", "dep_add", "dep_rm"]
READ = MAIN_TOOLS[:9]


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
    assert set(tools) == set(MAIN_TOOLS)
    assert out[0]["result"]["serverInfo"]["name"] == "strata-main"
    assert all("role" not in t["inputSchema"]["properties"] and t["inputSchema"]["type"] == "object" for t in tools.values())
    assert out[3]["error"]["code"] == -32601 and out[4]["error"]["code"] == -32700


def test_tools_and_role_fixed(tmp_path):
    p = str(tmp_path / "m.db")
    r, out = run(tmp_path, "coder", [
        call(1, "add_item", project="p", kind="issue", title="bug zork", role="main"),  # role arg ignored
        call(2, "add_item", project="p", kind="task", title="nope"),
        call(3, "search", q="zork")], p)
    assert r.returncode == 0 and r.stdout.count("\n") == 3  # server survived every error
    flags = [o.get("result", {}).get("isError") for o in out]
    assert flags == [False, True, False]
    assert json.loads(out[2]["result"]["content"][0]["text"].splitlines()[0])["title"] == "bug zork"
    c = db.connect(p)
    assert c.execute("SELECT created_by FROM item WHERE id=1").fetchone()[0] == "coder"
    assert {r[0] for r in c.execute("SELECT actor_role FROM audit WHERE tool='item.add'")} == {"coder"}


def test_bad_role(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), "mcp", "--role", "root", "--db", str(tmp_path / "x.db")], input="", capture_output=True, text=True)
    assert r.returncode != 0 and r.stdout == ""


def test_malformed_input_never_crashes(tmp_path):
    bad = [call(1, "add_item", project="p", kind="issue", title=5),
           {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": [1]},
           {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": [1]}},
           {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": ["x"]}},
           '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"item_claim","arguments":{"id":1e23}}}',
           '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"search","arguments":{"q":"a","limit":1e400}}}',
           call(7, "item_claim", id=True), call(8, "item_claim", id=10**30), call(9, "search", q=["a"]),
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


# ---- task #44: role filtering, read tools, cap, protocol, pipe ----
def tool_names(tmp_path, role):
    _, out = run(tmp_path, role, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    return {t["name"] for t in out[0]["result"]["tools"]}


def test_tools_list_by_role(tmp_path):
    assert tool_names(tmp_path, "main") == set(MAIN_TOOLS)
    coder, rev = tool_names(tmp_path, "coder"), tool_names(tmp_path, "reviewer")
    assert set(READ) <= coder and {"item_claim", "item_submit", "add_item"} <= coder
    assert not coder & {"edit_item", "item_approve", "dep_add"}
    assert rev == set(READ) | {"add_item"}
    _, out = run(tmp_path, "reviewer", [call(1, "item_claim", id=1)])
    assert out[0]["error"]["code"] == -32602  # hidden tools are not callable


def seeded(tmp_path):
    p = str(tmp_path / "s.db")
    c = db.init(p); db.add_project(c, "p", "P", docs_dir=str(tmp_path / "docs"))
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "a.yaml").write_text("title: A\nblocks:\n  - {type: md, text: hi}\n", encoding="utf-8")
    a = db.add_item(c, "p", "task", "first", "body one", "high", "approved"); b = db.add_item(c, "p", "task", "second", None, None, "approved")
    c.execute("INSERT INTO item_dep VALUES(?,?)", (b, a)); c.commit()
    c.close()
    return p


def test_read_tools(tmp_path):
    p = seeded(tmp_path)
    r, out = run(tmp_path, "reviewer", [call(1, "list_projects"), call(2, "list_items", project="p", ready=True), call(3, "get_item", id=2),
                                        call(4, "get_doc", project="p", path="a.yaml"), call(5, "c4_context", project="p"),
                                        call(6, "c4_flow", project="p"), call(7, "audit", project="p", limit=2), call(8, "search", q="first"),
                                        call(9, "get_doc", project="p", path="../x.yaml")], p)
    t = [o["result"]["content"][0]["text"] for o in out]
    flags = [o["result"]["isError"] for o in out]
    assert flags[:4] == [False] * 4 and flags[6:8] == [False] * 2 and flags[8]  # c4 tools may error: no model imported
    assert '"id": "p"' in t[0]
    assert [json.loads(l)["title"] for l in t[1].splitlines()] == ["first"]  # second is blocked by first
    i = json.loads(t[2].split("\n--- body ---")[0]); assert i["depends_on"][0]["id"] == 1 and "links" in i and i["audit"]
    d = json.loads(t[3]); assert d["title"] == "A" and d["errors"] == []
    assert len(t[6].splitlines()) == 2


def test_cap_line_boundary(tmp_path):
    p = seeded(tmp_path)
    c = db.connect(p); c.execute("UPDATE item SET body=? WHERE id=1", ("line of text\n" * 2000,)); c.commit(); c.close()
    _, out = run(tmp_path, "main", [call(1, "get_item", id=1)], p)
    t = out[0]["result"]["content"][0]["text"]
    assert len(t) <= 8000 and "… truncated, " in t and t.endswith("more chars; narrow with limit/filters")
    body, foot = t.rsplit("\n", 1)
    assert foot.startswith("… truncated") and body.endswith("line of text")  # cut on a line boundary


def test_protocol(tmp_path):
    msgs = [{"jsonrpc": "2.0", "id": i, "method": "initialize", "params": {"protocolVersion": v}} for i, v in enumerate(["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "1999-01-01"])]
    msgs += [{"jsonrpc": "2.0", "id": 9}, {"jsonrpc": "2.0", "id": 10, "method": 5}, '{"jsonrpc":"2.0","id":null,"method":"ping"}', '{"jsonrpc":"2.0","id":true,"method":"ping"}',
             '{"jsonrpc":"2.0","id":{"a":1},"method":"ping"}', '{"jsonrpc":"2.0","id":[1],"method":"ping"}', {"jsonrpc": "2.0", "id": "s", "method": "ping"}]
    _, out = run(tmp_path, "coder", msgs)
    assert [o["result"]["protocolVersion"] for o in out[:5]] == ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2025-11-25"]
    assert out[0]["result"]["serverInfo"]["name"] == "strata-coder"
    assert [o["error"]["code"] for o in out[5:11]] == [-32600] * 6 and out[11]["result"] == {}


def raw(tmp_path, data, role="coder"):
    p = str(tmp_path / "r.db"); db.init(p).close()
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), "mcp", "--role", role, "--db", p], input=data, capture_output=True, timeout=60)
    return r, [json.loads(l) for l in r.stdout.decode("ascii").splitlines()]


def test_bad_utf8_and_huge_line(tmp_path):
    ping = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    r, out = raw(tmp_path, b'\xff\xfe{"id":1}\n' + ping)
    assert r.returncode == 0 and out[0]["error"]["code"] == -32700 and out[1]["result"] == {}
    r, out = raw(tmp_path, b'{"x":"' + b"a" * (1 << 20) + b'"}\n' + ping + b'\xc3"\n')
    assert out[0]["error"]["code"] == -32600 and out[1]["result"] == {}
    assert out[2]["error"]["code"] == -32700 and r.returncode == 0
    r, out = raw(tmp_path, b"x" * (3 << 20))  # no newline at all: one error, clean exit
    assert out[0]["error"]["code"] == -32600 and len(out) == 1


def test_pipe_coder_denied_and_allowed(tmp_path):
    p = seeded(tmp_path)
    r, out = run(tmp_path, "coder", [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "add_item", project="p", kind="task", title="not allowed"),
        call(4, "item_claim", id=1, actor="bot"), call(5, "item_submit", id=1, note="done it", actor="bot")], p)
    assert out[0]["result"]["serverInfo"]["name"] == "strata-coder" and len(out) == 5
    assert "item_claim" in [t["name"] for t in out[1]["result"]["tools"]]
    assert out[2]["result"]["isError"] and out[3]["result"]["isError"] is False and out[4]["result"]["isError"] is False
    c = db.connect(p)
    assert c.execute("SELECT count(*) FROM audit WHERE tool LIKE 'denied:%' AND actor_role='coder'").fetchone()[0] == 1
    assert tuple(c.execute("SELECT status,owner FROM item WHERE id=1").fetchone()) == ("review", "bot")


def test_mcp_json():
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert {k: v["args"][-1] for k, v in cfg.items()} == {"strata": "main", "strata-coder": "coder", "strata-reviewer": "reviewer"}
    assert all(v["command"] == "python3" and v["args"][0].endswith("/strata.py") and v["args"][1] == "mcp" for v in cfg.values())


def test_expected_errors_one_stderr_line_and_hidden_tool_audited(tmp_path):
    p = seeded(tmp_path)
    r, out = run(tmp_path, "coder", [call(1, "item_submit", id=1, note="x"), call(2, "item_approve", id=1), call(3, "get_item", id=999)], p)
    assert out[0]["result"]["isError"] and out[1]["error"]["code"] == -32602 and out[2]["result"]["isError"]
    assert "Traceback" not in r.stderr and len(r.stderr.strip().splitlines()) == 2  # submit (not owner) + get_item KeyError
    c = db.connect(p)
    assert c.execute("SELECT count(*) FROM audit WHERE tool='denied:item_approve' AND actor_role='coder'").fetchone()[0] == 1


def test_task_context_all_roles(tmp_path):
    p = seeded(tmp_path)
    for role in ("main", "coder", "reviewer"):
        r, out = run(tmp_path, role, [call(1, "task_context", id=1, budget=500)], p)
        assert out[0]["result"]["isError"] is False and len(out[0]["result"]["content"][0]["text"]) <= 500


def test_label_issue_and_filter(tmp_path):
    p = seeded(tmp_path)
    r, out = run(tmp_path, "reviewer", [
        call(1, "add_item", project="p", kind="task", title="bug a", label="issue"),
        call(2, "add_item", project="p", kind="task", title="plain"),
        call(3, "add_item", project="p", kind="issue", title="bug b"),
        call(4, "list_items", project="p", label="issue")], p)
    flags = [o["result"]["isError"] for o in out]
    assert flags == [False, True, False, False]
    c = db.connect(p)
    rows = c.execute("SELECT kind,label,status FROM item WHERE title LIKE 'bug %'").fetchall()
    assert [tuple(x) for x in rows] == [("task", "issue", "proposed")] * 2
    assert sorted(json.loads(l)["title"] for l in out[3]["result"]["content"][0]["text"].splitlines()) == ["bug a", "bug b"]
