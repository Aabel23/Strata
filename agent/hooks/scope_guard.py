#!/usr/bin/env python3
"""PreToolUse hook: confine file edits to the paths listed in the nearest `.task-scope`.

No `.task-scope` above the target: allow. Blocks with exit 2. Applies to Edit-type tools only,
so Bash writes are not covered (accident prevention, not a sandbox). Malformed input fails open.
"""
import json
import os
import sys

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

try:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") not in EDIT_TOOLS:
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
except SystemExit:
    raise
except Exception:
    sys.exit(0)

# Scope files are looked up from the cwd and from the target (lexical and real path); every one found is enforced.
lexical = os.path.normpath(os.path.join(cwd, target)) if target else os.path.normpath(cwd)
target = os.path.realpath(lexical)

def scope_root(start):
    d = start if os.path.isdir(start) else os.path.dirname(start)
    while not os.path.isfile(os.path.join(d, ".task-scope")):
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)
    return os.path.realpath(d)

def block(msg):
    print("scope_guard: " + msg, file=sys.stderr)
    sys.exit(2)

roots = {r for r in (scope_root(os.path.normpath(cwd)), scope_root(lexical), scope_root(target)) if r}
for root in sorted(roots):
    if target == os.path.join(root, ".task-scope"):
        block(".task-scope is read-only for agents")
    try:
        with open(os.path.join(root, ".task-scope"), encoding="utf-8") as f:
            allowed = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except (OSError, UnicodeError) as e:
        block(f"cannot read {root}/.task-scope ({e})")
    for a in allowed:
        p = os.path.realpath(os.path.join(root, a))
        if (target == p or target.startswith(p.rstrip("/") + "/")) and (target == root or target.startswith(root + "/")):
            break
    else:
        block(f"{target} is outside the task scope ({root}/.task-scope)")
sys.exit(0)
