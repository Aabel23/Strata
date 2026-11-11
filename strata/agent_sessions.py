"""Observe Claude/Codex CLI processes and associate Strata-owned PTYs."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import json
import time


def _process(pid: int, proc_root: Path) -> dict | None:
    try:
        root = proc_root / str(pid)
        stat = (root / "stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        argv = (root / "cmdline").read_bytes().split(b"\0")
        if not argv or not argv[0]:
            return None
        return {"pid": pid, "ppid": int(fields[1]), "tty": int(fields[4]),
                "start": int(fields[19]), "name": os.path.basename(os.fsdecode(argv[0])),
                "args": [os.fsdecode(x) for x in argv[1:] if x],
                "cwd": os.readlink(root / "cwd"), "uid": (root / "stat").stat().st_uid}
    except (OSError, ValueError, IndexError):
        return None


def _branch(cwd: str) -> str | None:
    try:
        result = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=cwd,
                                capture_output=True, text=True, timeout=1, check=False,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _task_for_cwd(cwd: str, runs) -> dict | None:
    matches = []
    for run in runs:
        worktree = run.get("worktree")
        if worktree and (cwd == worktree or cwd.startswith(worktree.rstrip(os.sep) + os.sep)):
            matches.append((len(worktree), run.get("started", 0), run))
    if not matches:
        return None
    run = max(matches, key=lambda row: (row[0], row[1]))[2]
    return {"id": run["item"], "title": run.get("title") or ""}


def _event_file() -> Path:
    chosen = os.environ.get("STRATA_AGENT_EVENT_FILE")
    if chosen:
        return Path(chosen)
    runtime = Path(f"/run/user/{os.getuid()}")
    return (runtime if runtime.is_dir() else Path.home() / ".local/state/strata") / "agent-events.jsonl"


def _hook_subagents(cards: list[dict], path: Path) -> list[dict]:
    try:
        with path.open("rb") as stream:
            start = max(0, path.stat().st_size - 2_000_000)
            stream.seek(start)
            if start:
                stream.readline()
            lines = stream.readlines()
    except OSError:
        return []
    active = {}
    cutoff = time.time() - 6 * 3600
    for line in lines:
        try:
            event = json.loads(line)
            if event.get("t", 0) < cutoff:
                continue
            key = (event["provider"], event["session"], event["agent"])
            if event.get("event") == "SubagentStart":
                active[key] = event
            elif event.get("event") == "SubagentStop":
                active.pop(key, None)
        except (ValueError, TypeError, KeyError):
            continue
    by_id = {c["id"]: c for c in cards}
    result = []
    for (provider, session, agent), event in active.items():
        parent = by_id.get(event.get("parent"))
        if not parent:
            candidates = [c for c in cards if c["kind"].lower() == provider and c.get("cwd") and
                          (event.get("cwd") == c["cwd"] or event.get("cwd", "").startswith(c["cwd"].rstrip(os.sep) + os.sep))]
            if len(candidates) != 1:
                continue
            parent = candidates[0]
        child = {"id": f"hook:{provider}:{session}:{agent}", "kind": provider.title() + " " + str(event.get("type") or "subagent"),
                 "status": "running", "task": parent.get("task"), "branch": parent.get("branch"), "cwd": event.get("cwd") or parent.get("cwd"),
                 "terminal": parent.get("terminal"), "parent": parent["id"], "source": "subagent"}
        if parent.get("run"):
            child["run"] = parent["run"]
        result.append(child)
    return result


def discover(terminals, runs=(), *, chat_cards=(), proc_root: Path = Path("/proc"), uid: int | None = None,
             event_path: Path | None = None) -> list[dict]:
    """One card per live CLI process or task run. Only owned PTYs can be reopened."""
    owner = os.getuid() if uid is None else uid
    roots = dict(terminals.process_roots())
    processes = {}
    try:
        entries = proc_root.iterdir()
        for entry in entries:
            if entry.name.isdecimal():
                p = _process(int(entry.name), proc_root)
                if p and p["uid"] == owner:
                    processes[p["pid"]] = p
    except OSError:
        pass
    terminal_for = {}
    for terminal_id, root_pid in roots.items():
        terminal_for[root_pid] = terminal_id
    changed = True
    while changed:
        changed = False
        for p in processes.values():
            if p["pid"] not in terminal_for and p["ppid"] in terminal_for:
                terminal_for[p["pid"]] = terminal_for[p["ppid"]]
                changed = True
    selected = {pid: p for pid, p in processes.items()
                if p["name"] in {"claude", "codex"} and (pid in terminal_for or p["tty"] != 0)
                and "app-server" not in p["args"]}
    branch_cache = {}
    cards = []
    for pid, p in selected.items():
        if p["cwd"] not in branch_cache:
            branch_cache[p["cwd"]] = _branch(p["cwd"])
        branch = branch_cache[p["cwd"]]
        parent = p["ppid"]
        while parent in processes and parent not in selected:
            parent = processes[parent]["ppid"]
        cards.append({"id": f"process:{pid}:{p['start']}", "kind": p["name"].title(),
                      "status": "running", "task": _task_for_cwd(p["cwd"], runs), "branch": branch, "cwd": p["cwd"],
                      "terminal": terminal_for.get(pid), "parent": f"process:{parent}:{selected[parent]['start']}" if parent in selected else None,
                      "source": "terminal" if pid in terminal_for else "external"})
    for run in runs:
        if run.get("status") != "running":
            continue
        cards.append({"id": "run:" + run["id"], "kind": "Claude", "status": run["status"],
                      "task": {"id": run["item"], "title": run.get("title") or ""},
                      "branch": run.get("branch"), "cwd": run.get("worktree"),
                      "terminal": None, "parent": None, "source": "run", "run": run["id"]})
    cards.extend(chat_cards)
    cards.extend(_hook_subagents(cards, event_path or _event_file()))
    return sorted(cards, key=lambda c: (c["parent"] is not None, c["kind"], c["id"]))
