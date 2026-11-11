"""The global Claude hook blocks PR creation, destructive remote pushes, and direct main pushes."""
import json
import pathlib
import subprocess
import sys

import pytest

HOOK = pathlib.Path(__file__).resolve().parents[1] / "agent" / "hooks" / "github_guard.py"


def check(command, cwd=None):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd) if cwd else None}),
                          text=True, capture_output=True, cwd=cwd)


@pytest.mark.parametrize("command", [
    "gh pr create --base main", "bash -c 'gh pr create --base main'", "gh api -X POST repos/o/r/pulls",
    "gh api repos/o/r/pulls -f title=test", "gh api repos/o/r/pulls --input payload.json",
    "git push origin --delete feat/a/b", "git push origin :feat/a/b", "git push --force origin HEAD", "git push origin HEAD:refs/heads/main",
    "git push origin main", "git push origin +HEAD:refs/heads/feat/a/b",
])
def test_forbidden(command):
    result = check(command)
    assert result.returncode == 2 and "github_guard:" in result.stderr


@pytest.mark.parametrize("command", [
    "git fetch origin main", "git pull --ff-only origin main", "git push origin HEAD:refs/heads/fix/app/menu_t4",
    "git status", "gh pr view 3", "echo 'gh pr create'", "git show --stat",
])
def test_ordinary(command):
    assert check(command).returncode == 0


def test_push_with_ci_change_needs_approved_task_contract(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("base\n")
    git("add", "README.md")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("switch", "-qc", "fix/ci/check_t7")
    ci = tmp_path / ".github/workflows/check.yml"
    ci.parent.mkdir(parents=True)
    ci.write_text("name: check\n")
    git("add", ".github/workflows/check.yml")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ci")
    command = "git push origin HEAD:refs/heads/fix/ci/check_t7"
    assert check(command, tmp_path).returncode == 2
    marker = tmp_path / ".strata-task-contract.json"
    marker.write_text('{"task_id":7,"ci_change_approved":true,"scope":{"touch":["src"]}}')
    assert check(command, tmp_path).returncode == 2
    marker.write_text('{"task_id":7,"ci_change_approved":true,"scope":{"touch":[".github/workflows"]}}')
    assert check(command, tmp_path).returncode == 0
