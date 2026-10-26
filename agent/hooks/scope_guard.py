#!/usr/bin/env python3
"""Constrain file editing tools using a coordinator-provisioned task contract marker.

The marker is JSON: {"task_id": ..., "mode": "implement", "scope":
{"module": ..., "touch": [repo-relative paths]}}. Its touch list is copied
from the assigned contract's scope.touch. STRATA_AGENT_ROLE=coder makes a
missing marker fail closed. This is an accident-prevention hook, not a sandbox.
"""
import json
import os
import sys

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
MARKER = ".strata-task-contract.json"


def block(message):
    print("scope_guard: " + message, file=sys.stderr)
    raise SystemExit(2)


def ancestors(path):
    d = os.path.realpath(path)
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while True:
        yield d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent


def find_marker(paths):
    found = set()
    for path in paths:
        for d in ancestors(path):
            marker = os.path.join(d, MARKER)
            if os.path.isfile(marker):
                found.add(os.path.realpath(marker))
    if len(found) > 1:
        block("multiple task contract markers apply to this edit")
    return next(iter(found), None)


def load_scope(marker):
    try:
        with open(marker, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        block(f"cannot read valid {MARKER} ({e})")
    if (not isinstance(data, dict) or not isinstance(data.get("task_id"), (str, int))
            or data.get("mode") != "implement"):
        block(f"{MARKER} must describe an implement task")
    scope = data.get("scope")
    paths = scope.get("touch") if isinstance(scope, dict) else None
    module = scope.get("module") if isinstance(scope, dict) else None
    if (not isinstance(module, str) or not module.strip() or not isinstance(paths, list)
            or not paths or any(not isinstance(p, str) or not p.strip() for p in paths)):
        block(f"{MARKER} has missing or malformed scope.touch")
    root = os.path.realpath(os.path.dirname(marker))
    allowed = []
    for item in paths:
        item = item.strip()
        if os.path.isabs(item) or any(part == ".." for part in item.replace("\\", "/").split("/")):
            block("scope.touch entries must be safe repo-relative paths")
        allowed.append(os.path.realpath(os.path.join(root, item)))
    return root, allowed


try:
    request = json.load(sys.stdin)
except Exception as e:
    # A hook invocation that cannot be interpreted must not silently authorize an edit.
    block(f"invalid hook input ({e})")

if request.get("tool_name") not in EDIT_TOOLS:
    sys.exit(0)
tool_input = request.get("tool_input")
if not isinstance(tool_input, dict):
    block("missing tool_input")
cwd = os.path.abspath(request.get("cwd") or os.getcwd())
raw_target = tool_input.get("file_path") or tool_input.get("notebook_path")
if not isinstance(raw_target, str) or not raw_target:
    block("edit tool has no target path")
lexical = os.path.abspath(os.path.join(cwd, raw_target))
target = os.path.realpath(lexical)
marker = find_marker((cwd, lexical, target))
is_coder = os.environ.get("STRATA_AGENT_ROLE", "").lower() == "coder"
if marker is None:
    if is_coder:
        block(f"coder edit has no coordinator-provisioned {MARKER}")
    sys.exit(0)
if target == marker:
    block(f"{MARKER} is read-only for agents")
root, allowed = load_scope(marker)
if target == root or not (target == root or target.startswith(root + os.sep)):
    block("target escapes task repository")
if not any(target == p or target.startswith(p.rstrip(os.sep) + os.sep) for p in allowed):
    block(f"{target} is outside contract scope.touch")
sys.exit(0)
