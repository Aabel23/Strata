import json
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parents[1] / "agent/hooks/ci_edit_guard.py"


def call(cwd, tool, data):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd), "tool_name": tool, "tool_input": data}),
                          text=True, capture_output=True).returncode


def test_ci_edit_needs_flag_and_scope_for_claude_and_codex(tmp_path):
    ci = tmp_path / ".github/workflows/check.yml"
    ci.parent.mkdir(parents=True)
    patch = {"command": "*** Begin Patch\n*** Add File: .github/workflows/check.yml\n+name: check\n*** End Patch"}
    assert call(tmp_path, "Write", {"file_path": str(ci)}) == 2
    assert call(tmp_path, "apply_patch", patch) == 2
    assert call(tmp_path, "apply_patch", {"patch": patch["command"]}) == 2
    assert call(tmp_path, "apply_patch", patch["command"]) == 2
    marker = tmp_path / ".strata-task-contract.json"
    marker.write_text(json.dumps({"task_id": 2, "mode": "implement", "ci_change_approved": True, "scope": {"module": "ci", "touch": ["src"]}}))
    assert call(tmp_path, "apply_patch", patch) == 2
    marker.write_text(json.dumps({"task_id": 2, "mode": "implement", "ci_change_approved": True, "scope": {"module": "ci", "touch": [".github/workflows"]}}))
    assert call(tmp_path, "Write", {"file_path": str(ci)}) == 0
    assert call(tmp_path, "apply_patch", patch) == 0
    assert call(tmp_path, "ApplyPatch", {"patch": patch["command"]}) == 0
    assert call(tmp_path, "apply_patch", {"command": "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"}) == 0
