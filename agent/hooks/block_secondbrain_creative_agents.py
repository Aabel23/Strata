#!/usr/bin/env python3
"""Best-effort PreToolUse guard against delegated private-memory access.

Matches literal inputs/tool names and relies on host agent identity fields.
Aliases, symlinks, subprocesses and missing metadata can evade it; malformed
payloads fail open. Role tool lists do not isolate files reachable by Read/Bash.
Use runtime filesystem/process/tool restrictions for an actual privacy boundary.
This hook is accident prevention, not proof of confidentiality.
"""
import json
import re
import sys

VAULT = re.compile(r"\.secondbrain", re.I)  # Require the dot: the hook filename itself must not match the bare word.
VAULT_TOOL = re.compile(r"^mcp__obsidian", re.I)

try:
    data = json.load(sys.stdin)
except Exception as e:
    print(f"block_secondbrain hook: JSON hỏng, cho qua ({e})", file=sys.stderr)
    sys.exit(0)

if not isinstance(data, dict) or not (data.get("agent_id") or data.get("agent_type")):
    sys.exit(0)

tool_input = data.get("tool_input")
if not (VAULT_TOOL.search(str(data.get("tool_name") or ""))
        or VAULT.search(json.dumps(tool_input if tool_input is not None else {}, ensure_ascii=False))):
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "Subagent không được truy cập secondbrain (quy tắc của user). "
            "Tự nghiên cứu từ code, tài liệu repo và nguồn bên ngoài; không tìm cách vòng qua."
        ),
    }
}, ensure_ascii=False))
