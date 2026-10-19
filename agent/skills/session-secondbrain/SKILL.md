---
name: session-secondbrain
description: Capture reusable lessons from a conversation when the user asks to close or save the session ("lưu md", "chốt phiên"), and retrieve relevant personal or project memory for a later task. Do not use for ordinary chat summaries.
---

# Session second brain

Vault: `/home/abel/.secondbrain/`, accessed only through Obsidian MCP (`mcp__obsidian__*`, vault-relative paths).

Core files (the only ones agents read by default):
- `HIEN_PHAP.md`: how to work and the workflow.
- `RAM.md`: tree of what is being worked on now.
- `OPEN.md`: important unresolved issues.

There is no `memory/` folder (cleared 2026-10-18). Do not create one. Long-term project knowledge will move to Strata; until then only these three files exist.

## Closing a session
1. Update `RAM.md`: add or modify current work, remove finished items. Keep it a short tree.
2. Update `OPEN.md`: add new unresolved issues, delete resolved ones.
3. If the user stated a new working rule, edit `HIEN_PHAP.md` (short, no history).
4. Decisions that matter beyond this session go into RAM.md as one line each (under the task they belong to). Do not write session logs.
5. Report briefly what changed. The request authorizes these writes.

Keep the three core files small. Never duplicate details from memory into them.
