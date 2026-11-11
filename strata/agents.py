"""Task agents: one supervised Claude Code run per approved task, ending in a pushed branch.

For a project with auto-run switched on, a ready task (approved, dependencies done)
is picked up without anyone asking. The runner, not the agent, owns every step that
touches the board or the remote:

  claim   the task moves to `doing`, owner `agent:claude` (through the service, audited)
  fetch   `git fetch origin`, so the work starts from what GitHub has now
  branch  a new worktree on `<action>/<scope>/<work>`, cut from the remote default branch
  work    Claude Code runs headless in that worktree and commits there
  verify  the runner checks the branch, the changed files and every other ref
  push    the runner pushes that one branch (never forced, never the default branch)
  report  the task moves to `review` with the agent's report and the branch link

Authority is limited in three layers. The agent's every tool call passes
`agent/hooks/agent_guard.py`. When bubblewrap is installed the agent process sees
the filesystem read-only except its worktree and the repository's git store, and
does not see the GitHub login. And because only the runner pushes, after `verify`,
nothing the agent does reaches the remote without those checks.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

from strata import claude_models, db, service
from strata.chat_claude import _child_env, _claude_executable

ACTOR = "agent:claude"
GUARD = pathlib.Path(__file__).resolve().parent.parent / "agent" / "hooks" / "agent_guard.py"
MODELS = claude_models.MODEL_IDS
EFFORTS = claude_models.EFFORT_IDS
LIVE = ("running",)
MAX_EVENTS = 3000
MAX_TEXT = 4000
KEEP_RUNS = 80
POLL = 5.0
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]  # the runner never runs repository hooks
SECRET_DIRS = (".ssh", ".config/gh", ".gnupg", ".aws", ".kube", ".docker")
SECRET_FILES = (".git-credentials", ".netrc", ".npmrc", ".pypirc")


class AgentError(RuntimeError):
    pass


class Blocked(AgentError):
    """The work exists but may not be pushed."""


class Stopped(AgentError):
    pass


def _slug(text: str, limit: int = 40) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")[:limit].strip("_") or "task"


def branch_name(item: dict[str, Any]) -> str:
    """Stable three-part task branch; the final part includes the Strata id for uniqueness."""
    spec = item.get("spec") or {}
    scope = spec.get("scope") if isinstance(spec.get("scope"), dict) else {}
    action = spec.get("action")
    if not isinstance(action, str) or action not in {"feat", "fix", "refactor", "docs", "test", "chore"}:
        action = "fix" if item.get("kind") == "issue" else "feat"
    module = _slug(str(scope.get("module") or item.get("project") or "project"), 32)
    work = _slug(str(item["title"]), 48)
    return f"{action}/{module}/{work}_t{item['id']}"


def _legacy_branch_name(item_id: int, title: str) -> str:
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")[:40].strip("-") or "task"
    return f"agent/{item_id}-{slug}"


def _paths_overlap(left: list[str], right: list[str]) -> bool:
    return any(a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
               for a in left for b in right)


def github_url(remote: str) -> str | None:
    """https://github.com/owner/repo for a GitHub remote in either URL form, else None."""
    found = re.fullmatch(r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?", remote.strip())
    return f"https://github.com/{found.group(1)}/{found.group(2)}" if found else None


def sandbox_available(run=subprocess.run) -> bool:
    if os.environ.get("STRATA_AGENT_SANDBOX") == "0" or not shutil.which("bwrap"):
        return False
    try:
        return run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def sandbox_command(worktree: pathlib.Path, git_dir: pathlib.Path, home: pathlib.Path) -> list[str]:
    """bubblewrap prefix: everything read-only, except the worktree, the repository's git store (minus its
    config and hooks), Claude Code's own state and caches. Credential locations are replaced by empty ones."""
    cmd = ["bwrap", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
           "--bind", str(worktree), str(worktree), "--bind", str(git_dir), str(git_dir)]
    for name in ("config", "hooks", "info"):
        if (git_dir / name).exists():
            cmd += ["--ro-bind", str(git_dir / name), str(git_dir / name)]
    for name in (".claude", ".claude.json", ".cache"):
        if (home / name).exists():
            cmd += ["--bind", str(home / name), str(home / name)]
    for name in SECRET_DIRS:
        if (home / name).is_dir():
            cmd += ["--tmpfs", str(home / name)]
    for name in SECRET_FILES:
        if (home / name).is_file():
            cmd += ["--ro-bind", "/dev/null", str(home / name)]
    runtime = pathlib.Path(f"/run/user/{os.getuid()}")
    if runtime.is_dir():
        cmd += ["--tmpfs", str(runtime)]  # no session bus: a desktop keyring cannot hand out the git password either
    return cmd + ["--chdir", str(worktree), "--"]


def build_prompt(item: dict[str, Any], project: str, branch: str, base: str) -> str:
    spec = item.get("spec") or {}
    scope = spec.get("scope") if isinstance(spec.get("scope"), dict) else {}
    lines = [f"You are a Strata task agent working alone on task #{item['id']} of project `{project}`.",
             f"This directory is a git worktree already on branch `{branch}`, cut from the latest `{base}`.", "",
             f"# Task #{item['id']}: {item['title']}"]
    if item.get("body"):
        lines += ["", str(item["body"])]
    for key, label in (("goal", "Goal"), ("acceptance", "Acceptance"), ("verify", "Verify")):
        if spec.get(key):
            value = spec[key]
            lines += ["", f"## {label}", "\n".join(f"- {v}" for v in value) if isinstance(value, list) else str(value)]
    if scope.get("touch"):
        lines += ["", "## Scope", "You may change only these paths:", *[f"- {p}" for p in scope["touch"]]]
    lines += ["", "# How to work",
              "- Stay in this worktree and on this branch. Do the task; do not widen it.",
              "- Run the verification the task names (or the project's tests) and read the results.",
              f"- Commit your work here with messages that start with `#{item['id']} `. Leave nothing uncommitted.",
              "- Do not push, fetch, switch branches or change git configuration: the runner pushes this branch after you finish.",
              "- A guard refuses actions outside your authority. Do not work around a refusal; mention it in the report.",
              "", "# Report",
              "End with a short report in plain prose: what you changed, what you ran to verify it and what it showed, "
              "and anything left undone or blocked. That report is posted on the task for the reviewer."]
    return "\n".join(lines)


class AgentSupervisor:
    def __init__(self, db_path=None, *, popen=subprocess.Popen, state_dir=None, sandbox: bool | None = None,
                 environ: dict[str, str] | None = None, max_parallel: int | None = None, timeout: int | None = None):
        self._db_path = db.db_path(db_path)
        self._popen, self._environ = popen, dict(os.environ if environ is None else environ)
        self._dir = pathlib.Path(state_dir) if state_dir else pathlib.Path(self._db_path + ".agents")
        self._sandbox = sandbox
        self._max = max_parallel or int(self._environ.get("STRATA_AGENT_MAX") or 2)
        self._timeout = timeout or int(self._environ.get("STRATA_AGENT_TIMEOUT") or 3600)
        self._lock = threading.RLock()
        self._setup_locks: dict[str, threading.Lock] = {}
        self._changed = threading.Condition(self._lock)
        self._conn = None
        self._runs: dict[str, dict[str, Any]] = {}
        self._auto: dict[str, bool] = {}
        self._model = self._effort = ""
        self._watcher = None
        self._closing = False
        self._load()

    # ---- state ----
    def _load(self) -> None:
        try:
            data = json.loads((self._dir / "state.json").read_text())
        except (OSError, ValueError):
            return
        self._auto = {str(k): bool(v) for k, v in (data.get("auto") or {}).items()}
        self._model = data.get("model") if data.get("model") in MODELS else ""
        self._effort = data.get("effort") if data.get("effort") in EFFORTS else ""
        for run in data.get("runs") or []:
            if isinstance(run, dict) and isinstance(run.get("id"), str):
                if run.get("status") in LIVE:  # the server stopped while this agent was working
                    run.update(status="interrupted", error="The server restarted during this run. Retry to continue on the same branch.", ended=run.get("ended") or time.time())
                self._runs[run["id"]] = {**run, "events": None, "seq": run.get("seq", 0), "proc": None}
        if any(self._auto.values()):
            self._ensure_watcher()

    def _save(self) -> None:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r["started"])[-KEEP_RUNS:]
            for old in set(self._runs) - {r["id"] for r in runs}:
                del self._runs[old]
            data = {"auto": self._auto, "model": self._model, "effort": self._effort,
                    "runs": [{k: v for k, v in r.items() if k not in ("events", "proc")} for r in runs]}
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                tmp = self._dir / "state.json.tmp"
                tmp.write_text(json.dumps(data, ensure_ascii=False))
                tmp.replace(self._dir / "state.json")
            except OSError:
                pass

    def _db(self):
        if self._conn is None:
            self._conn = db.connect(self._db_path, check_same_thread=False)
        return self._conn

    def _ensure_watcher(self) -> None:
        with self._lock:
            if self._watcher is None and not self._closing:
                self._watcher = threading.Thread(target=self._watch, daemon=True)
                self._watcher.start()

    # ---- public surface (the server's routes) ----
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            runs = [{k: v for k, v in r.items() if k not in ("events", "proc")} for r in sorted(self._runs.values(), key=lambda r: -r["started"])]
            return {"auto": dict(self._auto), "model": self._model, "effort": self._effort, **claude_models.catalog(),
                    "max_parallel": self._max, "sandbox": self._sandbox_on(), "runs": runs, "now": time.time()}

    def set_auto(self, project: str, on: bool) -> None:
        with self._lock:
            self._project_root(project)  # raises for an unknown project or one without a repository
            self._auto[project] = bool(on)
            self._save()
        if on:
            self._ensure_watcher()

    def configure(self, model: str, effort: str) -> None:
        if not claude_models.effort_ok(model, effort):
            raise AgentError("unknown model, or an effort this model does not take")
        with self._lock:
            self._model, self._effort = model, effort
            self._save()

    def start(self, item_id: int) -> str:
        """Give one task to an agent now (also the retry: a task the agent still owns continues on its branch)."""
        with self._lock:
            if self._closing:
                raise AgentError("the server is shutting down")
            if any(r["item"] == item_id and r["status"] in LIVE for r in self._runs.values()):
                raise AgentError("an agent is already working on this task")
            if sum(r["status"] in LIVE for r in self._runs.values()) >= self._max:
                raise AgentError(f"{self._max} agents are already running; wait for one to finish")
            item = service.get_item(self._db(), item_id)
            if item["kind"] not in ("task", "step"):
                raise AgentError("only tasks are given to agents")
            if not (item["status"] in ("approved", "open") or (item["status"] == "doing" and item["owner"] == ACTOR)):
                raise AgentError(f"task is {item['status']}" + (f" (owner {item['owner']})" if item.get("owner") else "") + "; an agent takes approved tasks")
            touch = self._touch(item)
            if any(r["status"] in LIVE and r["project"] == item["project"] and
                   (not touch or not r.get("touch") or _paths_overlap(touch, r["touch"])) for r in self._runs.values()):
                raise AgentError("another active task touches the same project paths")
            previous = max((r for r in self._runs.values() if r["item"] == item_id and r.get("branch")),
                           key=lambda r: r["started"], default=None)
            run = {"id": secrets.token_urlsafe(9), "project": item["project"], "item": item_id, "title": item["title"], "status": "running", "phase": "claim",
                   "branch": previous["branch"] if previous else None, "base": None, "worktree": None, "started": time.time(), "ended": None, "error": None, "url": None, "commits": 0,
                   "files": 0, "model": self._model, "effort": self._effort, "used_model": None, "touch": touch,
                   "seq": 0, "events": collections.deque(maxlen=MAX_EVENTS), "proc": None, "stop": False}
            self._runs[run["id"]] = run
            self._save()
        threading.Thread(target=self._execute, args=(run,), daemon=True).start()
        return run["id"]

    def stop(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run["status"] not in LIVE:
                return False
            run["stop"] = True
            proc = run["proc"]
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
        return True

    def events(self, run_id: str, after: int = 0, wait: float = 0) -> dict[str, Any]:
        with self._changed:
            run = self._runs.get(run_id)
            if run is None:
                raise AgentError("no such run")
            if wait and run["status"] in LIVE:
                self._changed.wait_for(lambda: run["seq"] > after or run["status"] not in LIVE, wait)
            if run["events"] is None:  # a run from before this server start: its log is on disk
                run["events"] = collections.deque(self._read_log(run_id), maxlen=MAX_EVENTS)
            return {"events": [e for e in run["events"] if e["seq"] > after], "status": run["status"], "phase": run["phase"]}

    def close(self) -> None:
        with self._lock:
            self._closing = True
            live = [r["id"] for r in self._runs.values() if r["status"] in LIVE]
        for run_id in live:
            self.stop(run_id)

    # ---- log ----
    def _read_log(self, run_id: str) -> list[dict[str, Any]]:
        try:
            with open(self._dir / "logs" / f"{run_id}.jsonl", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()][-MAX_EVENTS:]
        except (OSError, ValueError):
            return []

    def _log(self, run: dict[str, Any], kind: str, text: str) -> None:
        with self._changed:
            run["seq"] += 1
            event = {"seq": run["seq"], "t": time.time(), "kind": kind, "text": str(text)[:MAX_TEXT]}
            run["events"].append(event)
            self._changed.notify_all()
        try:
            (self._dir / "logs").mkdir(parents=True, exist_ok=True)
            with open(self._dir / "logs" / f"{run['id']}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _phase(self, run: dict[str, Any], phase: str, text: str) -> None:
        with self._lock:
            if run["stop"]:
                raise Stopped("stopped")
            run["phase"] = phase
        self._log(run, "step", text)

    # ---- trusted git (the runner's own commands, with the user's credentials) ----
    def _git(self, cwd, *args: str, timeout: int = 120, check: bool = True) -> str:
        env = {**self._environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            done = subprocess.run([*GIT, *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise AgentError(f"git {args[0]} timed out") from exc
        except OSError as exc:
            raise AgentError("git is not available") from exc
        if check and done.returncode:
            raise AgentError(f"git {args[0]} failed: " + (done.stderr.strip() or done.stdout.strip())[-400:])
        return done.stdout.strip()

    def _project_root(self, project: str) -> pathlib.Path:
        row = self._db().execute("SELECT coalesce(nullif(p.root,''),m.root) root FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (project,)).fetchone()
        if not row or not row["root"]:
            raise AgentError(f"project {project} has no source folder registered")
        path = pathlib.Path(row["root"]).expanduser()
        if not path.is_dir():
            raise AgentError(f"project folder {path} does not exist")
        return pathlib.Path(self._git(path, "rev-parse", "--show-toplevel"))

    def _sandbox_on(self) -> bool:
        if self._sandbox is None:
            self._sandbox = sandbox_available()
        return self._sandbox

    # ---- auto-run ----
    def _watch(self) -> None:
        while not self._closing:
            time.sleep(POLL)
            try:
                with self._lock:
                    projects = [p for p, on in self._auto.items() if on]
                    for project in projects:
                        busy = {r["item"] for r in self._runs.values() if r["status"] in LIVE}
                        if len(busy) >= self._max:
                            break
                        ready = [i for i in service.list_items(self._db(), project=project, ready=True) if i["id"] not in busy]
                        for candidate in ready:
                            try:
                                self.start(candidate["id"])
                                break
                            except AgentError:
                                continue  # try another ready task with disjoint paths
            except Exception:
                pass  # a bad project or a busy database must not end the watcher

    # ---- one run ----
    def _execute(self, run: dict[str, Any]) -> None:
        item_id = run["item"]
        try:
            self._phase(run, "claim", f"Taking task #{item_id}: {run['title']}")
            with self._lock:
                item = service.get_item(self._db(), item_id)
                if item["status"] in ("approved", "open"):
                    service.transition(self._db(), "coder", item_id, "doing", actor=ACTOR)
                elif not (item["status"] == "doing" and item["owner"] == ACTOR):
                    raise AgentError(f"task is {item['status']}; nothing to take")
                root = self._project_root(run["project"])
            self._phase(run, "fetch", "Fetching origin")
            with self._lock:
                setup_lock = self._setup_locks.setdefault(str(root), threading.Lock())
            with setup_lock:
                remote = self._git(root, "remote", "get-url", "origin")
                self._git(root, "fetch", "origin", "--prune", timeout=300)
                head = self._git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
                base = head if head.startswith("origin/") else next((b for b in ("origin/main", "origin/master") if self._git(root, "rev-parse", "--verify", "-q", b, check=False)), None)
                with self._lock:
                    sibling_active = any(other is not run and other["project"] == run["project"] and other["status"] in LIVE
                                         for other in self._runs.values())
                if base and not sibling_active and self._git(root, "symbolic-ref", "--short", "HEAD", check=False) == base.split("/", 1)[1] and not self._git(root, "status", "--porcelain"):
                    try:
                        self._git(root, "pull", "--ff-only", "origin", base.split("/", 1)[1], timeout=300)
                        self._log(run, "info", "Fast-forwarded the clean main checkout")
                    except AgentError as exc:
                        self._log(run, "info", "Local main could not fast-forward; using fresh " + base + ": " + str(exc)[:180])
            if not base:
                raise AgentError("origin has no default branch to start from")
            old_branch = _legacy_branch_name(item_id, run["title"])
            branch = run.get("branch") or (old_branch if self._git(root, "rev-parse", "--verify", "-q", "refs/heads/" + old_branch, check=False) else branch_name(item))
            worktree = root.parent / ".strata-worktrees" / run["project"] / branch
            legacy_worktree = root.parent / ".strata-worktrees" / run["project"] / f"task-{item_id}"
            with self._lock:
                run.update(branch=branch, base=base, worktree=str(worktree))
            self._phase(run, "branch", f"Branch {branch} from {base}")
            if legacy_worktree.exists() and not worktree.exists():
                if self._git(legacy_worktree, "symbolic-ref", "--short", "HEAD") != branch:
                    raise AgentError(f"legacy worktree {legacy_worktree} is not on {branch}")
                worktree.parent.mkdir(parents=True, exist_ok=True)
                self._git(root, "worktree", "move", str(legacy_worktree), str(worktree))
            if worktree.exists():
                current = self._git(worktree, "symbolic-ref", "--short", "HEAD")
                if current != branch:
                    raise AgentError(f"worktree {worktree} is on {current}, not {branch}")
                self._log(run, "info", "Continuing in the existing worktree")
            else:
                worktree.parent.mkdir(parents=True, exist_ok=True)
                if self._git(root, "rev-parse", "--verify", "-q", "refs/heads/" + branch, check=False):
                    self._git(root, "worktree", "add", str(worktree), branch)
                else:
                    self._git(root, "worktree", "add", "--no-track", "-b", branch, str(worktree), base)
            worktree = worktree.resolve()
            git_dir = pathlib.Path(self._git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"))
            base_sha = self._git(worktree, "merge-base", "HEAD", base)
            refs_before, config_before = self._refs(root), self._config(git_dir)
            touch = self._touch(item)

            self._phase(run, "work", "Agent working" + (" in the sandbox" if self._sandbox_on() else " (no sandbox: bubblewrap is not usable here)"))
            report = self._run_claude(run, item, worktree, git_dir, branch, base, touch)

            self._phase(run, "verify", "Checking the work before pushing")
            if self._config(git_dir) != config_before:
                if config_before["config"] is not None:
                    (git_dir / "config").write_bytes(config_before["config"])
                raise Blocked("the repository's git configuration was changed during the run; it was restored and nothing was pushed")
            if self._git(worktree, "symbolic-ref", "--short", "HEAD", check=False) != branch:
                raise Blocked(f"the worktree is no longer on {branch}; nothing was pushed")
            if self._git(worktree, "status", "--porcelain"):
                self._git(worktree, "add", "-A")
                self._git(worktree, "commit", "-m", f"#{item_id} {run['title']}"[:200])
                self._log(run, "info", "Committed the changes the agent left uncommitted")
            commits = int(self._git(worktree, "rev-list", "--count", f"{base_sha}..HEAD") or 0)
            if not commits:
                raise AgentError("the agent finished without changing anything" + (": " + report[:300] if report else ""))
            files = [f for f in self._git(worktree, "diff", "--name-only", base_sha, "HEAD").splitlines() if f]
            in_touch = lambda f: any(f == t or f.startswith(t + "/") for t in touch)
            ci_approved = (item.get("spec") or {}).get("ci_change_approved") is True
            outside = [f for f in files if touch and not in_touch(f)] + [f for f in files if f.startswith(".github/workflows/") and not (ci_approved and in_touch(f))]
            if outside:
                raise Blocked("changes outside the task's scope, nothing was pushed: " + ", ".join(sorted(set(outside))[:12]))
            refs_after = self._refs(root)
            with self._lock:
                sibling_refs = {
                    "refs/heads/" + other["branch"] for other in self._runs.values()
                    if other is not run and other["project"] == run["project"] and other.get("branch")
                    and (other.get("ended") is None or other["ended"] >= run["started"])
                    and other.get("touch") and touch and not _paths_overlap(touch, other["touch"])
                }
            moved = sorted(r for r in set(refs_before) | set(refs_after)
                           if refs_before.get(r) != refs_after.get(r)
                           and r not in ("refs/heads/" + branch, "refs/stash") and r not in sibling_refs)
            if moved:
                raise Blocked("other refs changed during the run, nothing was pushed: " + ", ".join(moved[:8]))
            with self._lock:
                run.update(commits=commits, files=len(files))

            self._phase(run, "push", f"Pushing {branch} to origin")
            self._git(worktree, "push", "origin", f"HEAD:refs/heads/{branch}", timeout=300)
            site = github_url(remote)
            url = f"{site}/compare/{base.split('/', 1)[1]}...{branch}" if site else None
            with self._lock:
                run["url"] = url

            self._phase(run, "report", "Reporting on the task")
            note = (report.strip()[:3000] or "The agent finished without a written report.") + \
                f"\n\nBranch `{branch}` pushed to origin: {commits} commit(s), {len(files)} file(s)." + (f"\n{url}" if url else "")
            with self._lock:
                service.transition(self._db(), "coder", item_id, "review", actor=ACTOR, note=note)
            self._finish(run, "pushed", None, f"Done: {branch} is on origin and task #{item_id} is in review")
        except Stopped:
            self._finish(run, "stopped", "Stopped by the user. The task stays with the agent; retry continues on the same branch.", "Stopped")
        except Blocked as exc:
            self._finish(run, "blocked", str(exc), "Blocked: " + str(exc))
        except Exception as exc:
            if run["stop"]:
                self._finish(run, "stopped", "Stopped by the user. The task stays with the agent; retry continues on the same branch.", "Stopped")
            else:
                self._finish(run, "failed", str(exc)[:600] or exc.__class__.__name__, "Failed: " + (str(exc)[:600] or exc.__class__.__name__))

    def _finish(self, run: dict[str, Any], status: str, error: str | None, text: str) -> None:
        self._log(run, "done" if status == "pushed" else "error", text)
        with self._changed:
            run.update(status=status, error=error, ended=time.time(), phase="done" if status == "pushed" else run["phase"], proc=None)
            self._save()
            self._changed.notify_all()

    @staticmethod
    def _touch(item: dict[str, Any]) -> list[str]:
        scope = (item.get("spec") or {}).get("scope")
        paths = scope.get("touch") if isinstance(scope, dict) else None
        return [p.strip().strip("/") for p in paths if isinstance(p, str) and p.strip()] if isinstance(paths, list) else []

    def _refs(self, root) -> dict[str, str]:
        out = self._git(root, "for-each-ref", "--format=%(refname) %(objectname)")
        return dict(line.split(" ", 1) for line in out.splitlines() if " " in line and not line.startswith("refs/remotes/"))

    @staticmethod
    def _config(git_dir: pathlib.Path) -> dict[str, bytes | None]:
        """What the runner's own git commands would obey: the repository config and its hook scripts."""
        try:
            config = (git_dir / "config").read_bytes()
        except OSError:
            config = None
        digest = hashlib.sha256()
        try:
            for path in sorted((git_dir / "hooks").iterdir()):
                digest.update(path.name.encode() + b"\0" + (path.read_bytes() if path.is_file() else b""))
        except OSError:
            pass
        return {"config": config, "hooks": digest.digest()}

    def _run_claude(self, run, item, worktree: pathlib.Path, git_dir: pathlib.Path, branch: str, base: str, touch: list[str]) -> str:
        settings = json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": f"python3 {GUARD}", "timeout": 15}]}]}})
        args = [_claude_executable(self._environ), "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions",
                "--settings", settings, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disallowedTools", "WebFetch,WebSearch,Agent,Task"]
        if run["model"]:
            args += ["--model", run["model"]]
        if run["effort"]:
            args += ["--effort", run["effort"]]
        if self._sandbox_on():
            args = sandbox_command(worktree, git_dir, pathlib.Path(self._environ.get("HOME") or pathlib.Path.home())) + args
        env = _child_env(self._environ)
        env.update(STRATA_AGENT_WORKTREE=str(worktree), STRATA_AGENT_TOUCH=json.dumps(touch),
                   STRATA_AGENT_CI_EDIT="1" if (item.get("spec") or {}).get("ci_change_approved") is True else "0", GIT_TERMINAL_PROMPT="0",
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0="")  # the agent's git has no way to authenticate
        try:
            proc = self._popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                               cwd=str(worktree), env=env, start_new_session=True)
        except OSError as exc:
            raise AgentError("could not start Claude Code") from exc
        with self._lock:
            run["proc"] = proc
        timer = threading.Timer(self._timeout, lambda: self._expire(run, proc))
        timer.daemon = True
        timer.start()
        report, failed, tail = "", None, collections.deque(maxlen=5)
        try:
            proc.stdin.write(build_prompt(item, run["project"], branch, base))
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    if line.strip():
                        tail.append(line.strip()[:300])
                    continue
                if not isinstance(message, dict):
                    continue
                kind = message.get("type")
                if kind == "system" and message.get("subtype") == "init":
                    with self._lock:
                        run["used_model"] = str(message.get("model") or "")[:80] or None
                    self._log(run, "info", f"Claude Code session started, model {message.get('model')}")
                elif kind in ("assistant", "user") and isinstance(message.get("message"), dict) and not message.get("parent_tool_use_id"):
                    content = message["message"].get("content")
                    for block in content if isinstance(content, list) else []:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text" and str(block.get("text") or "").strip():
                            self._log(run, "text", block["text"])
                        elif block.get("type") == "tool_use":
                            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                            arg = next((str(tool_input[k]) for k in ("command", "file_path", "path", "pattern", "description") if tool_input.get(k)), "")
                            self._log(run, "tool", f"{block.get('name')} {arg}".strip())
                        elif block.get("type") == "tool_result":
                            out = block.get("content")
                            if isinstance(out, list):
                                out = "\n".join(str(x.get("text", "")) for x in out if isinstance(x, dict))
                            out = str(out or "").strip()
                            if block.get("is_error"):
                                self._log(run, "denied" if "agent_guard" in out else "error", out[:1200])
                            elif out:
                                self._log(run, "result", out[:600])
                elif kind == "result":
                    report = str(message.get("result") or "")
                    if message.get("is_error") or message.get("subtype") != "success":
                        failed = report[:600] or str(message.get("subtype") or "the agent run failed")
            code = proc.wait()
        finally:
            timer.cancel()
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # anything the agent left running in its process group
            except OSError:
                pass
            with self._lock:
                run["proc"] = None
        if run["stop"]:
            raise Stopped("stopped")
        if run.get("timed_out"):
            raise AgentError(f"the agent ran longer than {self._timeout // 60} minutes and was stopped")
        if failed:
            raise AgentError(failed)
        if code:
            raise AgentError(f"Claude Code exited with status {code}" + (": " + " | ".join(tail) if tail else ""))
        return report

    def _expire(self, run, proc) -> None:
        with self._lock:
            run["timed_out"] = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass


_SUPERVISORS: dict[str, AgentSupervisor] = {}
_SUPERVISORS_LOCK = threading.Lock()


def supervisor(db_path=None) -> AgentSupervisor:
    """One supervisor per database in this process: every bound address shows and drives the same agents."""
    key = db.db_path(db_path)
    with _SUPERVISORS_LOCK:
        if key not in _SUPERVISORS:
            _SUPERVISORS[key] = AgentSupervisor(key)
        return _SUPERVISORS[key]


__all__ = ["ACTOR", "AgentError", "AgentSupervisor", "build_prompt", "github_url", "sandbox_available", "sandbox_command", "supervisor"]
