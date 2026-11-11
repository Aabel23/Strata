#!/usr/bin/env python3
"""Require an approved task contract for editing GitHub CI workflow files."""
import json
import os
import re
import sys

MARKER = ".strata-task-contract.json"


def deny(message):
    print("ci_edit_guard: " + message + " Ask the coordinator to approve the CI change in the task contract.", file=sys.stderr)
    raise SystemExit(2)


def ci_path(path):
    return "/.github/workflows/" in path.replace(os.sep, "/")


def find_contract(path):
    directory = os.path.dirname(path)
    while True:
        marker = os.path.join(directory, MARKER)
        if os.path.isfile(marker):
            try:
                with open(marker, encoding="utf-8") as stream:
                    return directory, json.load(stream)
            except (OSError, ValueError):
                deny("the task contract is invalid.")
        parent = os.path.dirname(directory)
        if parent == directory:
            return None, None
        directory = parent


def check(path):
    lexical = os.path.abspath(path)
    if not ci_path(lexical):
        return
    path = os.path.realpath(lexical)
    if not ci_path(path):
        deny("a CI path may not resolve through a symlink outside the workflow directory.")
    root, contract = find_contract(path)
    if not root or not isinstance(contract, dict) or contract.get("ci_change_approved") is not True:
        deny("CI workflow edits need ci_change_approved: true.")
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    scope = contract.get("scope") or {}
    touch = scope.get("touch") if isinstance(scope, dict) else None
    if not isinstance(touch, list) or not any(isinstance(p, str) and (rel == p.strip("/") or rel.startswith(p.strip("/") + "/")) for p in touch):
        deny("the CI file must also be inside scope.touch.")


def main():
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name")
        data = payload.get("tool_input") or {}
        cwd = os.path.realpath(payload.get("cwd") or os.getcwd())
        if tool in ("apply_patch", "ApplyPatch"):
            patch = data if isinstance(data, str) else next((data.get(k) for k in ("command", "patch", "input") if isinstance(data.get(k), str)), None)
            if not isinstance(patch, str):
                deny("the patch input could not be read.")
            paths = re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.MULTILINE)
            paths += re.findall(r"^\*\*\* Move to: (.+)$", patch, re.MULTILINE)
        elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            if not isinstance(data, dict):
                deny("the edit input could not be read.")
            paths = [data.get("file_path") or data.get("notebook_path")]
        else:
            return
        for raw in paths:
            if not isinstance(raw, str) or not raw:
                deny("the edited path could not be read.")
            check(os.path.join(cwd, raw))
    except (TypeError, ValueError):
        deny("invalid hook input.")


if __name__ == "__main__":
    main()
