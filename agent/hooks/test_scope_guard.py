"""Subprocess tests for the PreToolUse scope guard; pytest-safe collection."""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_guard.py")
MARKER = ".strata-task-contract.json"


def run(tool, path, cwd, coder=True):
    env = os.environ.copy()
    if coder:
        env["STRATA_AGENT_ROLE"] = "coder"
    else:
        env.pop("STRATA_AGENT_ROLE", None)
    p = subprocess.run(
        [sys.executable, HOOK], text=True, capture_output=True, env=env,
        input=json.dumps({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": cwd}),
    )
    return p.returncode


def marker(root, payload):
    with open(os.path.join(root, MARKER), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def contract(touch=None):
    return {"task_id": "test", "mode": "implement", "scope": {"module": "agent", "touch": ["agent/hooks"] if touch is None else touch}}


def test_missing_and_malformed_scope_fail_closed_for_coder():
    with tempfile.TemporaryDirectory() as t:
        assert run("Write", "x", t) == 2
        marker(t, {"task_id": "test", "mode": "implement", "scope": {"touch": "agent"}})
        assert run("Write", "x", t) == 2


def test_enforces_contract_touch_and_safe_paths():
    with tempfile.TemporaryDirectory() as t:
        root = os.path.realpath(t)
        os.makedirs(os.path.join(root, "agent/hooks/sub"))
        os.makedirs(os.path.join(root, "agent/scripts"))
        outside = os.path.join(root, "outside")
        os.makedirs(outside)
        marker(root, contract(["agent/hooks"]))
        assert run("Edit", "agent/hooks/file.py", root) == 0
        assert run("Write", "agent/hooks/sub/new.py", root) == 0
        assert run("Edit", "agent/scripts/land.sh", root) == 2
        assert run("Write", "agent/hooks2/a.py", root) == 2
        assert run("Edit", "agent/hooks/../scripts/a.py", root) == 2
        assert run("Write", MARKER, root) == 2
        os.symlink(outside, os.path.join(root, "agent/hooks/link"))
        assert run("Write", "agent/hooks/link/escape.py", root) == 2
        assert run("Bash", "outside/file", root) == 0


def test_marker_can_be_found_from_nested_cwd_and_contract_paths_are_validated():
    with tempfile.TemporaryDirectory() as t:
        root = os.path.realpath(t)
        nested = os.path.join(root, "agent/hooks")
        os.makedirs(nested)
        marker(root, contract(["agent/hooks"]))
        assert run("Write", "x.py", nested) == 0
        marker(root, contract(["../outside"]))
        assert run("Write", "x.py", nested) == 2


def test_non_coder_without_marker_remains_unrestricted():
    with tempfile.TemporaryDirectory() as t:
        assert run("Write", "x.py", t, coder=False) == 0
