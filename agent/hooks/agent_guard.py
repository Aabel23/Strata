#!/usr/bin/env python3
"""PreToolUse guard for a Strata task agent: keep it inside its worktree, its branch and its task.

The agent runner (strata/agents.py) starts Claude Code with this hook and these variables:
  STRATA_AGENT_WORKTREE  absolute path of the task worktree (required; the hook fails closed without it)
  STRATA_AGENT_TOUCH     JSON list of repo-relative paths from the task's scope.touch (optional)

What it allows: reading the project, editing files inside the worktree (inside scope.touch when
the task has one), running commands there, and a short list of local git subcommands
(status, diff, add, commit, ...). What it refuses: every other tool (web, MCP, subagents),
pushing or reconfiguring git, switching branches, the GitHub CLI, privilege and remote-access
commands, the Strata CLI and database, credential files, and writes outside the worktree.

It is one of three layers and the only one that argues with the agent. The other two do not
depend on parsing shell text: the runner starts the agent in a filesystem sandbox when
bubblewrap is installed, and only the runner pushes, after checking the branch, the changed
files and every other ref.
"""
import json
import os
import re
import shlex
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Glob", "Grep"}
OTHER_TOOLS = {"Bash", "BashOutput", "KillShell", "KillBash", "TodoWrite"}
GIT_OK = {"status", "diff", "log", "show", "add", "commit", "restore", "rm", "mv", "stash", "blame", "grep", "ls-files",
          "rev-parse", "branch", "describe", "shortlog", "cat-file", "ls-tree", "apply", "check-ignore", "diff-tree",
          "merge-base", "rev-list", "name-rev", "whatchanged", "--version", "version", "help"}
GIT_BRANCH_OK = {"--show-current", "-a", "--all", "-v", "-vv", "--list", "-l", "-r", "--remotes", "--no-color", "--contains", "--merged", "--no-merged"}
DENIED_COMMANDS = {
    "gh": "the GitHub CLI is the runner's job", "sudo": "no privilege changes", "su": "no privilege changes", "doas": "no privilege changes",
    "ssh": "no remote access", "scp": "no remote access", "sftp": "no remote access", "rsync": "no remote copies", "nc": "no raw network tools",
    "ncat": "no raw network tools", "curl": "no downloads or uploads", "wget": "no downloads or uploads", "systemctl": "no service control",
    "service": "no service control", "crontab": "no scheduled jobs", "at": "no scheduled jobs", "shutdown": "no machine control", "reboot": "no machine control",
    "mount": "no mounts", "umount": "no mounts", "chown": "no ownership changes", "docker": "no containers", "podman": "no containers",
    "kubectl": "no cluster access", "strata": "the Strata board is the runner's job", "strata.py": "the Strata board is the runner's job",
    "bwrap": "no sandbox tools", "unshare": "no sandbox tools", "nsenter": "no sandbox tools", "claude": "no nested agents", "codex": "no nested agents",
}
SECRET_PARTS = (".ssh", ".config/gh", ".git-credentials", ".netrc", ".gnupg", ".aws", ".claude/.credentials", ".claude.json", ".config/systemd",
                ".docker/config.json", ".npmrc", ".pypirc", ".kube")
PROTECTED_TEXT = ("strata.db", "strata.py", ".git/config", ".git/hooks", ".git/info", "agent_guard")
WRITERS = {"rm", "mv", "cp", "ln", "chmod", "tee", "dd", "truncate", "install", "mkdir", "rmdir", "touch", "shred"}
COPIERS = {"cp", "ln", "install"}  # their sources may be anywhere readable; only the destination (last word) is checked
WRAPPERS = {"bash", "sh", "zsh", "dash", "eval"}
STOP = "Do not work around this; if the task needs it, say so in your final report and stop."


def block(message):
    print("agent_guard: " + message + " " + STOP, file=sys.stderr)
    raise SystemExit(2)


def inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def secret(path):
    home = os.path.realpath(os.path.expanduser("~"))
    return any(inside(path, os.path.join(home, part)) for part in SECRET_PARTS + (".claude/.credentials.json",))


def resolve(raw, cwd):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(raw)))


def check_edit(target, root, touch):
    if not inside(target, root) or target == root:
        block(f"{target} is outside the task worktree {root}.")
    rel = os.path.relpath(target, root)
    parts = rel.split(os.sep)
    if parts[0] in (".git", ".claude") or rel == ".strata-task-contract.json":
        block(f"{rel} is not the agent's to change.")
    in_touch = any(rel == t or rel.startswith(t.rstrip("/") + "/") for t in touch)
    if parts[:2] == [".github", "workflows"] and not (in_touch and os.environ.get("STRATA_AGENT_CI_EDIT") == "1"):
        block("CI workflows change only when scope.touch names them and the approved task explicitly allows CI edits.")
    if touch and not in_touch:
        block(f"{rel} is outside the task's scope.touch. You may edit: {', '.join(touch)}.")


def words(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        block("this command has unbalanced quotes, so it cannot be checked.")


def check_git(args):
    sub = None
    for i, arg in enumerate(args):
        if arg in ("-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace") or arg.startswith(("--git-dir=", "--work-tree=", "-c", "-C")):
            block("git runs only in the task worktree with its own configuration (no -C, -c, --git-dir, --work-tree).")
        if not arg.startswith("-") or arg in ("--version",):
            sub, rest = arg, args[i + 1:]
            break
    if sub is None:
        return
    if sub not in GIT_OK:
        hint = {"push": "The runner pushes your branch after you finish.", "checkout": "Use `git restore` for files; the branch is fixed.",
                "switch": "The branch is fixed.", "pull": "The worktree was created from the fresh remote base.",
                "fetch": "The worktree was created from the fresh remote base."}.get(sub, "")
        block(f"`git {sub}` is not allowed for a task agent. {hint}".strip())
    if sub == "branch" and any(a not in GIT_BRANCH_OK for a in rest):
        block("`git branch` is read-only here: the task branch already exists and is the only one you commit to.")
    if sub == "commit" and "--amend" in rest:
        block("`git commit --amend` is not allowed: earlier commits may already be pushed. Add a new commit.")
    if sub == "stash" and rest[:1] and rest[0] not in ("push", "pop", "apply", "list", "show", "drop", "save", "-u", "--include-untracked", "-m"):
        block(f"`git stash {rest[0]}` is not allowed.")


def check_command(text, cwd, root, depth=0):
    if depth > 4:
        block("this command nests too deeply to be checked.")
    low = text.lower()
    for part in SECRET_PARTS:
        if part in text:
            block(f"commands may not touch credential locations ({part}).")
    for part in PROTECTED_TEXT:
        if part in low:
            block(f"commands may not touch {part}.")
    for inner in re.findall(r"\$\(([^()]*)\)", text) + re.findall(r"`([^`]*)`", text):
        check_command(inner, cwd, root, depth + 1)
    tokens = words(text)
    command, redirect = None, False  # command: first word of the current simple command
    for i, token in enumerate(tokens):
        if token and all(ch in ";&|()\n" for ch in token):
            command = None
            continue
        if token and all(ch in "<>" for ch in token):
            redirect = ">" in token
            continue
        if redirect:
            redirect = False
            target = resolve(token, cwd)
            if not (inside(target, root) or inside(target, "/tmp") or target.startswith("/dev/")):
                block(f"output may be redirected only inside the worktree or /tmp, not to {token}.")
            continue
        base = os.path.basename(token)
        if command is None:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) or token in ("env", "command", "exec", "nohup", "time", "nice", "xargs", "then", "do", "else", "!", "{"):
                continue  # still looking for the command word
            command = base
            if base in DENIED_COMMANDS:
                block(f"`{base}` is not allowed for a task agent: {DENIED_COMMANDS[base]}.")
            if base in WRAPPERS:
                rest = tokens[i + 1:]
                script = rest[rest.index("-c") + 1] if "-c" in rest and rest.index("-c") + 1 < len(rest) else (" ".join(rest) if base == "eval" else None)
                if script:
                    check_command(script, cwd, root, depth + 1)
        if base == "git":
            end = next((j for j in range(i + 1, len(tokens)) if tokens[j] and all(ch in ";&|()\n" for ch in tokens[j])), len(tokens))
            check_git(tokens[i + 1:end])
        elif base in DENIED_COMMANDS and command != base:
            block(f"`{base}` is not allowed for a task agent: {DENIED_COMMANDS[base]}.")
        elif command in WRITERS and command != base and not token.startswith("-") and (token.startswith(("/", "~")) or ".." in token.split("/")):
            last = i + 1 == len(tokens) or (tokens[i + 1] and all(ch in ";&|()<>\n" for ch in tokens[i + 1]))
            if command in COPIERS and not last:
                continue
            target = resolve(token, cwd)
            if not (inside(target, root) or inside(target, "/tmp") or target.startswith("/dev/")):
                block(f"`{command}` may only change files inside the worktree or /tmp, not {token}.")


def main():
    root = os.environ.get("STRATA_AGENT_WORKTREE")
    if not root or not os.path.isabs(root):
        block("STRATA_AGENT_WORKTREE is not set, so nothing can be checked.")
    root = os.path.realpath(root)
    try:
        touch = json.loads(os.environ.get("STRATA_AGENT_TOUCH") or "[]")
        request = json.load(sys.stdin)
        tool, tool_input = request["tool_name"], request.get("tool_input") or {}
        if not isinstance(touch, list) or not isinstance(tool_input, dict) or not isinstance(tool, str):
            raise ValueError("unexpected shape")
    except SystemExit:
        raise
    except Exception as exc:
        block(f"the hook input could not be read ({exc}).")
    touch = [t.strip().strip("/") for t in touch if isinstance(t, str) and t.strip()]
    cwd = os.path.realpath(request.get("cwd") or root)
    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(raw, str) or not raw:
            block("this edit has no target path.")
        check_edit(resolve(raw, cwd), root, touch)
    elif tool in READ_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(raw, str) and raw and secret(resolve(raw, cwd)):
            block("credential files are not readable by a task agent.")
    elif tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            block("this command could not be read.")
        if not inside(cwd, root):
            block(f"commands run inside the task worktree {root}, not {cwd}.")
        check_command(command, cwd, root)
    elif tool not in OTHER_TOOLS:
        block(f"the {tool} tool is not available to a task agent (files and shell only).")


if __name__ == "__main__":
    main()
