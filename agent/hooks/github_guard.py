#!/usr/bin/env python3
"""Claude PreToolUse accident guard for GitHub mutations reserved for CI or the owner.

This is a command-level warning barrier, not a security boundary. Repository branch
protection and separate credentials must enforce the same policy remotely.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def deny(reason):
    print("github_guard: " + reason + " Use the Strata task pipeline; do not work around this hook.", file=sys.stderr)
    raise SystemExit(2)


def check_ci_diff(cwd):
    def git(*args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=3, check=False,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    try:
        root = git("rev-parse", "--show-toplevel")
        if root.returncode or git("rev-parse", "--verify", "origin/main").returncode:
            return
        changed = git("diff", "--no-ext-diff", "--name-only", "--diff-filter=ACMR", "origin/main...HEAD")
    except (OSError, subprocess.TimeoutExpired):
        deny("the pending push could not be checked for CI changes.")
    if changed.returncode:
        deny("the pending push could not be checked for CI changes.")
    ci_files = [p for p in changed.stdout.splitlines() if p.startswith(".github/workflows/")]
    if not ci_files:
        return
    marker = Path(root.stdout.strip()) / ".strata-task-contract.json"
    try:
        contract = json.loads(marker.read_text())
        touch = contract["scope"]["touch"]
        approved = contract.get("ci_change_approved") is True and isinstance(touch, list)
    except (OSError, ValueError, KeyError, TypeError):
        approved = False
        touch = []
    if not approved or any(not any(isinstance(p, str) and (f == p.strip("/") or f.startswith(p.strip("/") + "/")) for p in touch) for f in ci_files):
        deny("CI workflow changes in a pushed branch need explicit task approval and scope.touch.")


def check_simple(words, cwd):
    while words and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]) or words[0] in ("env", "command", "exec", "nohup")):
        words = words[1:]
    if not words:
        return
    binary = os.path.basename(words[0])
    args = words[1:]
    if binary in ("bash", "sh", "zsh", "dash") and "-c" in args:
        i = args.index("-c")
        if i + 1 < len(args):
            check(args[i + 1], cwd)
    if binary == "gh":
        if "pr" in args and "create" in args[args.index("pr") + 1:]:
            deny("PR creation belongs to CI after checks pass.")
        if "api" in args and any(a in ("POST", "PUT", "PATCH", "DELETE", "-f", "-F", "--field", "--raw-field", "--input")
                                 or a.startswith(("--method=", "--field=", "--raw-field=", "--input=", "-f=", "-F=")) for a in args):
            deny("mutating GitHub API calls are reserved for the CI bot or owner.")
    if binary != "git":
        return
    # Git global flags can precede the subcommand. Reject unknown shapes instead of
    # trying to infer whether a destructive push is hidden behind them.
    if "push" not in args:
        return
    if "-C" in args or any(a.startswith("-C") for a in args):
        deny("run git push from the task worktree so its CI diff can be checked.")
    push = args[args.index("push") + 1:]
    if any(a in ("--delete", "-d", "--force", "-f", "--force-with-lease", "--mirror", "--all") or a.startswith(("--force=", "--force-with-lease=")) for a in push):
        deny("force pushes and remote branch deletion are reserved for the owner.")
    if any(a.startswith("+") or a.startswith(":") or a.endswith((":refs/heads/main", ":main")) or a in ("main", "refs/heads/main") for a in push):
        deny("remote deletion and direct pushes to main are blocked.")
    check_ci_diff(cwd)


def check(command, cwd):
    for inner in re.findall(r"\$\(([^()]*)\)", command) + re.findall(r"`([^`]*)`", command):
        check(inner, cwd)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        deny("unbalanced shell quoting cannot be checked.")
    current = []
    for token in tokens + [";"]:
        if token and all(c in ";&|()<>\n" for c in token):
            if current:
                check_simple(current, cwd)
                current = []
        else:
            current.append(token)


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str):
            deny("missing shell command.")
        check(command, payload.get("cwd") or os.getcwd())
    except (TypeError, ValueError, KeyError):
        deny("invalid hook input.")


if __name__ == "__main__":
    main()
