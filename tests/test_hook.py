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


def test_bare_word_in_hook_filename_allowed():
    assert not run({"agent_type": "coder", "tool_name": "Bash", "tool_input": {"command": "ls agent/hooks/block_secondbrain_creative_agents.py"}})


def test_dotted_vault_path_denied():
    assert run({"agent_type": "coder", "tool_name": "Bash", "tool_input": {"command": "cat ~/.secondbrain/RAM.md"}})


def test_install_hooks_dry_run_apply_idempotent(tmp_path):
    script = HOOK.parent.parent / "scripts/install_hooks.py"
    f = tmp_path / "settings.json"
    codex = tmp_path / "codex-hooks.json"
    old = {"permissions": {"allow": ["x"]}, "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /elsewhere/block_secondbrain_creative_agents.py"}]}]}}
    f.write_text(json.dumps(old))
    go = lambda *a: subprocess.run([sys.executable, str(script), "--settings", str(f), "--codex-settings", str(codex), *a], capture_output=True, text=True, check=True).stdout
    assert "would add: scope_guard.py" in go() and json.loads(f.read_text()) == old  # dry run writes nothing
    assert "added: scope_guard.py" in go("--apply") and "already registered: block_secondbrain" in go("--apply")
    new = json.loads(f.read_text())
    assert new["permissions"] == old["permissions"] and new["hooks"]["PreToolUse"][0] == old["hooks"]["PreToolUse"][0] and len(new["hooks"]["PreToolUse"]) == 4
    assert new["hooks"]["PreToolUse"][1]["hooks"][0]["command"].endswith("agent/hooks/scope_guard.py") and json.loads((tmp_path / "settings.json.bak").read_text()) == old
    assert len(json.loads(codex.read_text())["hooks"]["PreToolUse"]) == 2
    assert json.loads(codex.read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"].endswith("agent/hooks/github_guard.py")
    assert len(json.loads(codex.read_text())["hooks"]["SubagentStart"]) == 1
    assert len(json.loads(codex.read_text())["hooks"]["SubagentStop"]) == 1
    assert "already registered: github_guard.py for Codex" in go("--apply")
