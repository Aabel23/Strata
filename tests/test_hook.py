import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "agent/hooks/block_secondbrain_creative_agents.py"


def run(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True)
    assert r.returncode == 0
    return "deny" in r.stdout


def test_subagent_obsidian_denied():
    assert run({"agent_type": "general-purpose", "tool_name": "mcp__obsidian__read_note", "tool_input": {"path": "RAM.md"}})


def test_subagent_bash_vault_denied():
    assert run({"agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "cat ~/.secondbrain/x"}})


def test_main_chat_allowed():
    assert not run({"tool_name": "Bash", "tool_input": {"command": "cat ~/.secondbrain/x"}})


def test_non_dict_and_bad_json_allowed():
    assert not run([1, 2])
    assert not run("{not json")


def test_missing_tool_input_no_crash():
    assert not run({"agent_type": "coder", "tool_name": "Read"})
