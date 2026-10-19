#!/usr/bin/env python3
"""PreToolUse: chặn subagent architect/researcher chạm vào ~/.secondbrain.

User yêu cầu (10/10/2026): architect và researcher không được truy cập secondbrain
để giữ sáng tạo và tìm kiến trúc ngoài vùng hiểu biết sẵn có của user.
"""
import json
import re
import sys

BLOCKED_ROLE = re.compile(r"architect|research", re.I)
VAULT = re.compile(r"secondbrain|second[\s_-]brain", re.I)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

agent_type = str(data.get("agent_type") or "")
if not BLOCKED_ROLE.search(agent_type):
    sys.exit(0)

VAULT_TOOL = re.compile(r"obsidian|mcpvault", re.I)  # MCP vault không mang đường dẫn trong input

if not (VAULT.search(json.dumps(data.get("tool_input") or {}, ensure_ascii=False))
        or VAULT_TOOL.search(str(data.get("tool_name") or ""))):
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Agent '{agent_type}' không được truy cập secondbrain (quy tắc của user). "
            "Tự nghiên cứu từ code, tài liệu repo và nguồn bên ngoài; không tìm cách vòng qua."
        ),
    }
}, ensure_ascii=False))
sys.exit(0)
