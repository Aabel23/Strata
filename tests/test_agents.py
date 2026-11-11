"""The task-agent runner end to end, with a scripted stand-in for Claude Code and a local bare repository as origin."""
import json
import os
import pathlib
import stat
import subprocess
import threading
import time

import pytest

from strata import agents, db, service

FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
prompt = sys.stdin.read()
conf = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake.json")))  # the child env is an allowlist
mode = conf["mode"]
say = lambda **m: print(json.dumps(m), flush=True)
say(type="system", subtype="init", model="fake-model", session_id="s1")
git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
if mode != "idle":
    path = {"ok": "src/new.py", "outside": "docs/stray.md", "dirty": "src/left.py"}.get(mode, "src/new.py")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").write("# task %d\n" % os.getpid())
    say(type="assistant", message={"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": path}}]})
    if mode != "dirty":
        git("add", "-A"); git("commit", "-m", "#1 work")
    if mode == "refs":
        git("branch", "sneaky")
    if mode == "config":
        git("config", "core.sshCommand", "evil")
open(conf["out"], "w").write(json.dumps({"prompt": prompt, "argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}))
say(type="assistant", message={"content": [{"type": "text", "text": "Implemented and verified."}]})
say(type="result", subtype="success", is_error=mode == "fail", result="Changed src/new.py; tests pass.")
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root = tmp_path / "work" / "proj"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("hi\n")
    git(root, "add", "-A"); git(root, "commit", "-qm", "init"); git(root, "remote", "add", "origin", str(origin)); git(root, "push", "-q", "-u", "origin", "main")
    fake = tmp_path / "claude"
    fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    dbp = tmp_path / "t.db"
    c = db.init(str(dbp)); db.add_project(c, "p", "P", root=str(root))
    spec = {"goal": "g", "acceptance": ["a"], "verify": ["pytest"], "scope": {"module": "m", "touch": ["src"]}}
    item = service.add_item(c, "main", "p", "task", "Add the new module", body="details", status="approved", spec=spec); c.commit(); c.close()
    out = tmp_path / "fake-out.json"

    def make(mode="ok", **kw):
        (tmp_path / "fake.json").write_text(json.dumps({"mode": mode, "out": str(out)}))
        env = {**os.environ, "STRATA_CLAUDE_BIN": str(fake), "ANTHROPIC_API_KEY": "sk-x", "GH_TOKEN": "t"}
        return agents.AgentSupervisor(str(dbp), sandbox=False, environ=env, state_dir=tmp_path / "state", **kw)
    return type("W", (), {"make": staticmethod(make), "origin": origin, "root": root, "db": dbp, "item": item, "out": out, "tmp": tmp_path})


def finish(sup, run_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        run = next(r for r in sup.snapshot()["runs"] if r["id"] == run_id)
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def status(w):
    c = db.connect(str(w.db)); r = c.execute("SELECT status,owner FROM item WHERE id=?", (w.item,)).fetchone(); c.close()
    return r["status"], r["owner"]


def test_approved_task_ends_as_a_pushed_branch_in_review(world):
    sup = world.make()
    run = finish(sup, sup.start(world.item))
    assert run["error"] is None, run["error"]
    assert run["status"] == "pushed" and run["error"] is None and run["commits"] == 1 and run["files"] == 1 and run["used_model"] == "fake-model"
    branch = f"feat/m/add_the_new_module_t{world.item}"
    assert run["branch"] == branch and git(world.origin, "rev-parse", "--verify", branch)
    assert git(world.origin, "rev-parse", "main") == git(world.root, "rev-parse", "main")  # the default branch did not move
    assert status(world) == ("review", agents.ACTOR)
    c = db.connect(str(world.db))
    notes = [json.loads(r["after"]).get("note") for r in c.execute("SELECT after FROM audit WHERE tool='item.transition' ORDER BY id")]
    assert "Changed src/new.py; tests pass." in notes[-1] and branch in notes[-1]
    seen = json.loads(world.out.read_text())
    assert seen["cwd"].endswith(f".strata-worktrees/p/{branch}") and "Add the new module" in seen["prompt"] and "- src" in seen["prompt"]
    argv = seen["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions" and "--strict-mcp-config" in argv
    assert "--model" not in argv and "--effort" not in argv
    hook = json.loads(argv[argv.index("--settings") + 1])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert hook.endswith("agent/hooks/agent_guard.py")
    env = seen["env"]
    assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env and env["STRATA_AGENT_WORKTREE"] == seen["cwd"] and json.loads(env["STRATA_AGENT_TOUCH"]) == ["src"]
    log = sup.events(run["id"])
    kinds = [e["kind"] for e in log["events"]]
    assert kinds[0] == "step" and "tool" in kinds and "text" in kinds and kinds[-1] == "done"
    again = agents.AgentSupervisor(str(world.db), sandbox=False, state_dir=world.tmp / "state")  # a restart keeps the history and the log
    assert again.snapshot()["runs"][0]["status"] == "pushed" and again.events(run["id"])["events"][-1]["kind"] == "done"


@pytest.mark.parametrize("dirty", [False, True])
def test_fetch_uses_fresh_main_and_only_fast_forwards_a_clean_checkout(world, dirty):
    other = world.tmp / "upstream"
    git(world.tmp, "clone", "-q", str(world.origin), str(other))
    (other / "FRESH.md").write_text("new from origin\n")
    git(other, "add", "FRESH.md")
    git(other, "commit", "-qm", "upstream")
    git(other, "push", "-q", "origin", "main")
    old_main = git(world.root, "rev-parse", "main")
    if dirty:
        (world.root / "README.md").write_text("local uncommitted work\n")
    sup = world.make()
    run = finish(sup, sup.start(world.item))
    assert run["status"] == "pushed", run["error"]
    assert git(run["worktree"], "cat-file", "-e", "HEAD:FRESH.md") == ""
    assert git(world.root, "rev-parse", "main") == (old_main if dirty else git(world.origin, "rev-parse", "main"))
    if dirty:
        assert (world.root / "README.md").read_text() == "local uncommitted work\n"


@pytest.mark.parametrize("mode,word", [("outside", "scope"), ("refs", "other refs"), ("config", "configuration")])
def test_work_that_oversteps_is_not_pushed(world, mode, word):
    sup = world.make(mode)
    run = finish(sup, sup.start(world.item))
    assert run["status"] == "blocked" and word in run["error"]
    assert git(world.origin, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
    assert status(world) == ("doing", agents.ACTOR)
    if mode == "config":
        assert "evil" not in (world.root / ".git" / "config").read_text()


def test_uncommitted_work_is_committed_and_no_work_fails(world):
    sup = world.make("dirty")
    run = finish(sup, sup.start(world.item))
    assert run["status"] == "pushed" and run["commits"] == 1
    c = db.connect(str(world.db)); other = service.add_item(c, "main", "p", "issue", "Nothing to do"); c.commit(); c.close()
    idle = world.make("idle")
    run = finish(idle, idle.start(other))
    assert run["status"] == "failed" and "without changing anything" in run["error"]


def test_failed_agent_keeps_the_task_and_retry_continues_on_the_branch(world):
    sup = world.make("fail")
    run = finish(sup, sup.start(world.item))
    assert run["status"] == "failed" and status(world) == ("doing", agents.ACTOR)
    retry = world.make()
    run = finish(retry, retry.start(world.item))  # the task is `doing`, owned by the agent: retry is allowed
    assert run["status"] == "pushed" and status(world)[0] == "review"
    with pytest.raises(agents.AgentError):
        retry.start(world.item)  # in review now: not the agent's any more


def test_legacy_task_worktree_moves_to_branch_named_folder(world):
    branch = f"agent/{world.item}-add-the-new-module"
    legacy = world.root.parent / ".strata-worktrees" / "p" / f"task-{world.item}"
    legacy.parent.mkdir(parents=True)
    git(world.root, "worktree", "add", "-b", branch, str(legacy), "main")
    sup = world.make()
    run = finish(sup, sup.start(world.item))
    assert run["status"] == "pushed", run["error"]
    moved = legacy.parent / branch
    assert not legacy.exists() and moved.is_dir()
    assert git(moved, "symbolic-ref", "--short", "HEAD") == branch


def test_auto_run_takes_ready_tasks_only_for_switched_on_projects(world, monkeypatch):
    monkeypatch.setattr(agents, "POLL", 0.05)
    sup = world.make()
    time.sleep(0.3)
    assert sup.snapshot()["runs"] == []  # off by default
    sup.set_auto("p", True)
    end = time.time() + 20
    while time.time() < end and not sup.snapshot()["runs"]:
        time.sleep(0.05)
    run = finish(sup, sup.snapshot()["runs"][0]["id"])
    assert run["status"] == "pushed" and run["item"] == world.item
    time.sleep(0.3)
    assert len(sup.snapshot()["runs"]) == 1  # the task left `approved`, so it is not taken twice
    with pytest.raises(agents.AgentError):
        sup.set_auto("missing", True)
    sup.close()


def test_disjoint_task_worktrees_run_together_and_overlapping_scope_waits(world):
    c = db.connect(str(world.db))
    spec = {"goal": "g", "acceptance": ["a"], "verify": ["git status"],
            "scope": {"module": "m", "touch": ["docs"]}}
    second = service.add_item(c, "main", "p", "task", "Update docs", status="approved", spec=spec)
    spec["scope"]["touch"] = ["src/subdir"]
    overlap = service.add_item(c, "main", "p", "task", "Update source too", status="approved", spec=spec)
    c.commit(); c.close()
    barrier = threading.Barrier(2)
    sup = world.make(max_parallel=2)

    def work(run, item, worktree, *_args):
        barrier.wait(timeout=10)
        rel = "src/new.py" if item["id"] == world.item else "docs/new.md"
        path = worktree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("task work\n")
        git(worktree, "add", rel)
        git(worktree, "commit", "-m", f"#{item['id']} work")
        return "Verified work in the assigned worktree."

    sup._run_claude = work
    first_id = sup.start(world.item)
    deadline = time.time() + 15
    while time.time() < deadline and next(r for r in sup.snapshot()["runs"] if r["id"] == first_id)["phase"] != "work":
        time.sleep(0.02)
    assert next(r for r in sup.snapshot()["runs"] if r["id"] == first_id)["phase"] == "work"
    with pytest.raises(agents.AgentError, match="same project paths"):
        sup.start(overlap)
    main_before = git(world.root, "rev-parse", "main")
    other = world.tmp / "upstream"
    git(world.tmp, "clone", "-q", str(world.origin), str(other))
    (other / "FRESH.md").write_text("main advanced\n")
    git(other, "add", "FRESH.md")
    git(other, "commit", "-qm", "upstream")
    git(other, "push", "-q", "origin", "main")
    second_id = sup.start(second)
    first_run, second_run = finish(sup, first_id), finish(sup, second_id)
    assert first_run["status"] == second_run["status"] == "pushed", (first_run["error"], second_run["error"])
    assert first_run["worktree"] != second_run["worktree"]
    assert git(world.origin, "rev-parse", first_run["branch"])
    assert git(world.origin, "rev-parse", second_run["branch"])
    assert git(world.root, "rev-parse", "main") == main_before  # a sibling run was active; no main update mid-run


def test_helpers():
    assert agents.branch_name({"id": 9, "kind": "issue", "project": "p", "title": "Menu sync bug edit", "spec": {"action": "fix", "scope": {"module": "app_menu_sync"}}}) == "fix/app_menu_sync/menu_sync_bug_edit_t9"
    assert agents.github_url("https://github.com/Aabel23/Strata.git") == "https://github.com/Aabel23/Strata"
    assert agents.github_url("git@github.com:o/r.git") == "https://github.com/o/r" and agents.github_url("/tmp/origin.git") is None
    cmd = agents.sandbox_command(pathlib.Path("/w/t"), pathlib.Path("/w/r/.git"), pathlib.Path("/nonexistent-home"))
    assert cmd[0] == "bwrap" and cmd[cmd.index("--ro-bind") + 1:cmd.index("--ro-bind") + 3] == ["/", "/"] and ["--bind", "/w/t", "/w/t"] == cmd[cmd.index("--bind"):cmd.index("--bind") + 3]
