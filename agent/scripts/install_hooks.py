#!/usr/bin/env python3
"""Register supported agent/hooks guards for Claude Code and Codex.

Dry run by default: prints what would be added. --apply writes the settings
file after copying it to <file>.bak. Idempotent: a hook whose script name is
already registered (any path, e.g. a symlink in ~/.claude/hooks) is left alone.
Other settings and hooks are preserved.
"""
import argparse
import json
import pathlib
import shutil

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
# script -> matcher (which tools the hook has to see)
WANT = {"block_secondbrain_creative_agents.py": "*", "scope_guard.py": "Edit|Write|NotebookEdit|MultiEdit", "github_guard.py": "Bash", "ci_edit_guard.py": "Edit|Write|NotebookEdit|MultiEdit"}
CODEX_WANT = {"github_guard.py": "^Bash$", "ci_edit_guard.py": "apply_patch|Edit|Write"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", default=str(pathlib.Path.home() / ".claude/settings.json"))
    ap.add_argument("--codex-settings", default=str(pathlib.Path.home() / ".codex/hooks.json"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    for host, path, wanted in (("Claude", pathlib.Path(a.settings), WANT), ("Codex", pathlib.Path(a.codex_settings), CODEX_WANT)):
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
        have = " ".join(h.get("command", "") for g in pre for h in g.get("hooks", []))
        todo = {s: m for s, m in wanted.items() if s not in have}
        for script, matcher in todo.items():
            pre.append({"matcher": matcher, "hooks": [{"type": "command", "command": f"python3 {HOOKS / script}"}]})
            print(f"{'added' if a.apply else 'would add'}: {script} for {host} (matcher {matcher})")
        for script in wanted.keys() - todo.keys():
            print(f"already registered: {script} for {host}")
        lifecycle_added = False
        for event in ("SubagentStart", "SubagentStop"):
            group = cfg["hooks"].setdefault(event, [])
            command = f"STRATA_AGENT_PROVIDER={host.lower()} python3 {HOOKS / 'subagent_event.py'}"
            if not any(command == h.get("command") for g in group for h in g.get("hooks", [])):
                group.append({"hooks": [{"type": "command", "command": command}]})
                lifecycle_added = True
                print(f"{'added' if a.apply else 'would add'}: subagent_event.py for {host} ({event})")
        if a.apply and (todo or lifecycle_added):
            if path.exists():
                shutil.copy2(path, str(path) + ".bak")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {path}; {host} hooks load in a new session")
        elif todo or lifecycle_added:
            print(f"dry run for {host}; pass --apply to write")


if __name__ == "__main__":
    main()
