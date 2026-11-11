#!/usr/bin/env python3
"""Record minimal Claude/Codex subagent lifecycle metadata for the Strata viewer."""
import fcntl
import json
import os
from pathlib import Path
import time
import sys


def event_file() -> Path:
    chosen = os.environ.get("STRATA_AGENT_EVENT_FILE")
    if chosen:
        return Path(chosen)
    runtime = Path(f"/run/user/{os.getuid()}")
    return (runtime if runtime.is_dir() else Path.home() / ".local/state/strata") / "agent-events.jsonl"


def cli_parent():
    pid = os.getppid()
    for _ in range(24):
        try:
            root = Path("/proc") / str(pid)
            stat = (root / "stat").read_text()
            fields = stat[stat.rfind(")") + 2:].split()
            argv0 = (root / "cmdline").read_bytes().split(b"\0", 1)[0]
            name = os.path.basename(os.fsdecode(argv0))
            if name in ("claude", "codex"):
                return f"process:{pid}:{int(fields[19])}"
            pid = int(fields[1])
            if pid <= 1:
                return None
        except (OSError, ValueError, IndexError):
            return None
    return None


def main():
    event = None
    provider = os.environ.get("STRATA_AGENT_PROVIDER") or "unknown"
    try:
        data = json.load(sys.stdin)
        event = data.get("hook_event_name")
        session, agent = data.get("session_id"), data.get("agent_id")
        if event not in ("SubagentStart", "SubagentStop") or not isinstance(session, str) or not isinstance(agent, str):
            return
        record = {"event": event, "session": session[:160], "agent": agent[:160],
                  "type": str(data.get("agent_type") or "subagent")[:80],
                  "provider": provider,
                  "parent": cli_parent(), "cwd": str(data.get("cwd") or "")[:1024], "t": time.time()}
        path = event_file()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError):
        pass  # telemetry must never interrupt a real agent
    finally:
        if provider == "codex" and event == "SubagentStop":
            print("{}")  # Codex requires JSON stdout for a successful stop hook.


if __name__ == "__main__":
    main()
