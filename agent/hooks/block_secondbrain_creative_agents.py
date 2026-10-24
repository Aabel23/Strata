#!/usr/bin/env python3
"""PreToolUse: subagent không được chạm vault secondbrain.

Best-effort: khớp chuỗi và tên tool, vòng được bằng glob/symlink. Kiểm soát thật là
allowlist `tools` trong agent/agents/*.md (subagent không có mcp__obsidian__*).
Subagent = payload có agent_id hoặc agent_type; chat chính (không có cả hai) được phép.
"""
import json
import re
import sys

VAULT = re.compile(r"\.secondbrain", re.I)  # cần dấu chấm đầu: tên file hook chứa từ trần không bị chặn
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
