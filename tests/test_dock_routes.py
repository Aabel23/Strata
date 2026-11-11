"""Routes behind the dock: terminals (real shells) and task agents. Guards first, then one real round trip."""
import base64, json, pathlib, shlex, threading, time, urllib.error, urllib.request
import pytest
from strata import agents, db, server, term


@pytest.fixture
def srv(tmp_path):
    p = tmp_path / "t.db"; c = db.init(str(p)); db.add_project(c, "a", "A", root=str(tmp_path)); c.close()
    made = []

    def make(**kw):
        sup = agents.AgentSupervisor(str(p), sandbox=False, state_dir=tmp_path / "state")
        s = server.make_server(p, None, 0, agent_supervisor=sup, terminals=term.TerminalManager(), **kw)
        threading.Thread(target=s.serve_forever, daemon=True).start(); made.append(s)
        return f"127.0.0.1:{s.server_address[1]}"
    yield make
    for s in made: s.shutdown(); s.server_close()


def call(hp, path, body=None, **hdr):
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: session = json.load(r)
    h = {"X-Strata-Token": session["token"], **({"X-Strata-Edit": "1", "Content-Type": "application/json"} if body is not None else {}), **hdr}
    h = {k: v for k, v in h.items() if v is not None}
    req = urllib.request.Request("http://" + hp + path, json.dumps(body).encode() if body is not None else None, h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_terminal_round_trip_and_guards(srv):
    hp = srv()
    with urllib.request.urlopen(f"http://{hp}/api/session") as r: assert json.load(r)["terminal"] is True
    assert call(hp, "/api/term", {"op": "open"}, **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, "/api/term", {"op": "open"}, **{"X-Strata-Edit": None})[0] == 403
    assert call(hp, "/api/term", {"op": "open"}, Origin="http://evil.test")[0] == 403
    assert call(hp, "/api/term", {"op": "open", "shell": "/bin/sh"})[0] == 400
    assert call(hp, "/api/term", {"op": "input", "id": "x" * 12, "data": "ls\n"})[0] == 409
    st, r = call(hp, "/api/term", {"op": "open", "project": "a", "cols": 80, "rows": 24})
    assert st == 200 and pathlib.Path(r["cwd"]).is_dir()
    tid = r["id"]
    assert call(hp, "/api/term/read?id=" + tid, **{"X-Strata-Token": "nope"})[0] == 403
    assert call(hp, "/api/term", {"op": "input", "id": tid, "data": "echo round-$((40+2))\n"})[0] == 200
    seen, after, end = b"", 0, time.time() + 15
    while b"round-42" not in seen and time.time() < end:
        st, r = call(hp, f"/api/term/read?id={tid}&after={after}")
        assert st == 200
        seen += base64.b64decode(r["data"]); after = r["next"]
    assert b"round-42" in seen
    assert call(hp, "/api/term", {"op": "resize", "id": tid, "cols": 120, "rows": 30})[0] == 200
    assert [t["id"] for t in call(hp, "/api/term", {"op": "list"})[1]["terminals"]] == [tid]
    assert call(hp, "/api/term", {"op": "close", "id": tid})[1]["closed"] is True
    assert call(hp, "/api/term", {"op": "list"})[1]["terminals"] == []


def test_terminal_is_off_where_editing_is_off_unless_asked(srv):
    off = srv(allow_edit=False)
    assert call(off, "/api/term", {"op": "open"})[0] == 403 and call(off, "/api/term/read?id=" + "x" * 12)[0] == 403
    assert call(off, "/api/agent", {"op": "settings", "model": "", "effort": ""})[0] == 403
    assert call(off, "/api/agents")[0] == 200  # watching agents is a read
    on = srv(allow_edit=False, allow_terminal=True)
    st, r = call(on, "/api/term", {"op": "open"})
    assert st == 200 and call(on, "/api/term", {"op": "close", "id": r["id"]})[0] == 200


def test_live_cli_in_terminal_appears_as_agent_card(srv):
    hp = srv()
    st, opened = call(hp, "/api/term", {"op": "open"})
    assert st == 200
    tid = opened["id"]
    try:
        assert call(hp, "/api/term", {"op": "input", "id": tid, "data": "bash -c 'exec -a claude sleep 20'\n"})[0] == 200
        end = time.time() + 8
        card = None
        while time.time() < end:
            sessions = call(hp, "/api/agents")[1]["sessions"]
            card = next((s for s in sessions if s["terminal"] == tid and s["kind"] == "Claude"), None)
            if card:
                break
            time.sleep(0.1)
        assert card and card["status"] == "running" and card["source"] == "terminal"
        assert card["task"] is None and card["parent"] is None
        assert "pid" not in card
        assert call(hp, "/api/agents")[1]["sessions"].count(card) == 1
    finally:
        call(hp, "/api/term", {"op": "input", "id": tid, "data": "\u0003"})
        call(hp, "/api/term", {"op": "close", "id": tid})


def test_child_cli_card_links_to_parent(srv, tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import subprocess\nsubprocess.run(['bash', '-c', 'exec -a codex sleep 20'])\n")
    hp = srv()
    st, opened = call(hp, "/api/term", {"op": "open"})
    assert st == 200
    tid = opened["id"]
    try:
        command = "bash -c " + shlex.quote("exec -a claude python3 " + shlex.quote(str(script))) + "\n"
        assert call(hp, "/api/term", {"op": "input", "id": tid, "data": command})[0] == 200
        end = time.time() + 8
        parent = child = None
        while time.time() < end:
            cards = [c for c in call(hp, "/api/agents")[1]["sessions"] if c["terminal"] == tid]
            parent = next((c for c in cards if c["kind"] == "Claude"), None)
            child = next((c for c in cards if c["kind"] == "Codex"), None)
            if parent and child:
                break
            time.sleep(0.1)
        assert parent and child and child["parent"] == parent["id"]
    finally:
        call(hp, "/api/term", {"op": "input", "id": tid, "data": "\u0003"})
        call(hp, "/api/term", {"op": "close", "id": tid})


def test_cli_in_known_task_worktree_gets_task_label(srv, tmp_path, monkeypatch):
    worktree = tmp_path / "task-worktree"
    worktree.mkdir()
    original = agents.AgentSupervisor.snapshot

    def snapshot(self):
        data = original(self)
        data["runs"] = [{"id": "past-run", "item": 42, "title": "Fix menu sync", "status": "pushed",
                         "branch": "fix/app_menu_sync/menu_sync_t42", "worktree": str(worktree), "started": 1}]
        return data

    monkeypatch.setattr(agents.AgentSupervisor, "snapshot", snapshot)
    hp = srv()
    st, opened = call(hp, "/api/term", {"op": "open"})
    assert st == 200
    tid = opened["id"]
    try:
        command = "cd " + shlex.quote(str(worktree)) + " && bash -c 'exec -a claude sleep 20'\n"
        assert call(hp, "/api/term", {"op": "input", "id": tid, "data": command})[0] == 200
        end = time.time() + 8
        card = None
        while time.time() < end:
            card = next((c for c in call(hp, "/api/agents")[1]["sessions"] if c["terminal"] == tid and c["kind"] == "Claude"), None)
            if card:
                break
            time.sleep(0.1)
        assert card and card["task"] == {"id": 42, "title": "Fix menu sync"}
    finally:
        call(hp, "/api/term", {"op": "input", "id": tid, "data": "\u0003"})
        call(hp, "/api/term", {"op": "close", "id": tid})


def test_native_subagent_hook_appears_under_cli_card(srv, tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("STRATA_AGENT_EVENT_FILE", str(events))
    monkeypatch.setenv("STRATA_AGENT_PROVIDER", "claude")
    hook = pathlib.Path(__file__).resolve().parents[1] / "agent/hooks/subagent_event.py"
    script = tmp_path / "parent.py"
    script.write_text("import json, subprocess, sys, time, os\n"
                      "payload = {'hook_event_name': 'SubagentStart', 'session_id': 's', 'agent_id': 'a', 'agent_type': 'Explore', 'cwd': os.getcwd()}\n"
                      f"subprocess.run(['python3', {str(hook)!r}], input=json.dumps(payload), text=True, check=True, env={{**os.environ, 'STRATA_AGENT_EVENT_FILE': {str(events)!r}, 'STRATA_AGENT_PROVIDER': 'claude'}})\n"
                      "time.sleep(20)\n")
    hp = srv()
    st, opened = call(hp, "/api/term", {"op": "open"})
    assert st == 200
    tid = opened["id"]
    try:
        command = "bash -c " + shlex.quote("exec -a claude python3 " + shlex.quote(str(script))) + "\n"
        assert call(hp, "/api/term", {"op": "input", "id": tid, "data": command})[0] == 200
        end = time.time() + 8
        parent = child = None
        while time.time() < end:
            cards = [c for c in call(hp, "/api/agents")[1]["sessions"] if c["terminal"] == tid]
            parent = next((c for c in cards if c["kind"] == "Claude"), None)
            child = next((c for c in cards if c["kind"] == "Claude Explore"), None)
            if parent and child:
                break
            time.sleep(0.1)
        assert parent and child and child["parent"] == parent["id"] and child["source"] == "subagent"
    finally:
        call(hp, "/api/term", {"op": "input", "id": tid, "data": "\u0003"})
        call(hp, "/api/term", {"op": "close", "id": tid})


def test_agent_routes(srv):
    hp = srv()
    assert call(hp, "/api/agents", **{"X-Strata-Token": None})[0] == 403
    st, d = call(hp, "/api/agents")
    assert st == 200 and d["runs"] == [] and d["auto"] == {} and "opus" in [m["id"] for m in d["models"]] and "xhigh" in [e["id"] for e in d["efforts"]]
    assert call(hp, "/api/agent", {"op": "settings", "model": "opus", "effort": "max"})[0] == 200
    assert call(hp, "/api/agent", {"op": "settings", "model": "gpt", "effort": ""})[0] == 409
    assert call(hp, "/api/agent", {"op": "auto", "project": "missing", "on": True})[0] == 409
    assert call(hp, "/api/agent", {"op": "auto", "project": "a", "on": "yes"})[0] == 400
    assert call(hp, "/api/agent", {"op": "run", "item": 99})[0] == 404
    assert call(hp, "/api/agent", {"op": "stop", "run": "x" * 12})[1]["stopped"] is False
    assert call(hp, "/api/agent/log?run=" + "x" * 12)[0] == 404
    assert call(hp, "/api/agents")[1]["model"] == "opus"
