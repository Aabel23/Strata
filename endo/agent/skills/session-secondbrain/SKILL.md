---
name: session-secondbrain
description: Capture reusable lessons from a conversation when the user asks to close or save the session ("lưu md", "chốt phiên"), and retrieve relevant personal or project memory for a later task. Do not use for ordinary chat summaries.
---

# Session second brain

Vault: `/home/abel/.secondbrain/`, accessed only through Obsidian MCP (`mcp__obsidian__*`, vault-relative paths).

Core files (the coordinator reads these at startup; delegated workers never do):
- `RAM.md`: tree of what is being worked on now.
- `OPEN.md`: important unresolved issues.

There is no `memory/` folder (cleared 2026-10-18). Do not create one. Long-term project knowledge will move to Strata; until then these are the two core continuity files.

## Closing a session
1. Update `RAM.md`: add or modify current work, remove finished items. Keep it a short tree.
2. Update `OPEN.md`: add new unresolved issues, delete resolved ones.
3. Do not promote transient notes, lessons or inferred preferences to permanent policy. Only when the user explicitly requests a policy change, delegate the scoped edit to the relevant layer under `/home/abel/project/tools/endo/agent/`, obtain independent review, and follow its local commit policy. Session-saving authorization alone does not authorize a rule change.
4. Decisions that matter beyond this session go into RAM.md as one line each (under the task they belong to). Do not write session logs.
5. Report briefly what changed. The session-saving request authorizes the continuity writes above; separate policy changes retain their own authorization.

Keep the two vault files small. Keep only current, useful continuity; link to project evidence instead of copying long documents.
