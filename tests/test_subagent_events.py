"""Claude/Codex lifecycle hooks create and clear native subagent cards."""
import json
import os
import pathlib
import subprocess
import sys

from strata import agent_sessions

HOOK = pathlib.Path(__file__).resolve().parents[1] / "agent/hooks/subagent_event.py"


def emit(path, event, cwd, provider="claude"):
    payload = {"hook_event_name": event, "session_id": "session-1", "agent_id": "child-1", "agent_type": "Explore", "cwd": str(cwd)}
    env = {**os.environ, "STRATA_AGENT_EVENT_FILE": str(path), "STRATA_AGENT_PROVIDER": provider}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_lifecycle_event_creates_child_card_on_shared_terminal(tmp_path):
    path = tmp_path / "events.jsonl"
    parent = {"id": "process:1:100", "kind": "Claude", "status": "running", "cwd": str(tmp_path),
              "terminal": "term-1", "task": {"id": 7, "title": "Menu sync"}, "branch": "fix/app_menu_sync/menu_t7"}
    emit(path, "SubagentStart", tmp_path)
    children = agent_sessions._hook_subagents([parent], path)
    assert len(children) == 1
    child = children[0]
    assert child["parent"] == parent["id"] and child["terminal"] == "term-1"
    assert child["task"] == parent["task"] and child["branch"] == parent["branch"]
    assert child["kind"] == "Claude Explore" and child["source"] == "subagent" and "pid" not in child
    emit(path, "SubagentStop", tmp_path)
    assert agent_sessions._hook_subagents([parent], path) == []


def test_codex_stop_hook_returns_required_json(tmp_path):
    out = emit(tmp_path / "events.jsonl", "SubagentStop", tmp_path, provider="codex")
    assert json.loads(out) == {}
