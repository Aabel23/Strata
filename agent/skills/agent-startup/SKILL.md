---
name: agent-startup
description: Run the full Strata/owner governance startup sweep for this session — read HIEN_PHAP.md and COORDINATOR.md (owner policy and coordinator duties), recall RAM.md/OPEN.md from the private vault via Obsidian MCP, read the project's own CLAUDE.md, and, when no narrower user request is active, triage the full Strata board and advance ready/approved work through WORKFLOW.md gates. Use this when the user explicitly asks to start/open a Strata or governed session, says things like "chạy agent startup", "nạp trí nhớ", "đọc HIEN_PHAP/COORDINATOR", "xem RAM/OPEN", "kiểm tra board strata", or wants the coordinator to pick up whatever's pending/approved without naming a specific task. Do NOT run this for an ordinary scoped request (a bug fix, a question about code, a one-off edit, or any request that already names what to do) — those proceed directly; this sweep is for when the user wants the governance context itself, or an open-ended "what's next" pass over the Strata board.
---

# Agent startup

Canonical governance lives in `/home/abel/project/tools/strata/agent/`. Resolve relative governance links and governance-file paths against that canonical agent directory, not an installed symlink directory or the current project's working directory. Project-relative and tool-repository paths keep their own stated bases.

Run in order:

1. Read [HIEN_PHAP.md](../../HIEN_PHAP.md) and [COORDINATOR.md](../../COORDINATOR.md).
2. Read `RAM.md` and `OPEN.md` in `/home/abel/.secondbrain` only through Obsidian MCP, using vault-relative paths. If the Obsidian MCP is unavailable, tell the user and continue from repository evidence instead of guessing at memory content.
3. Read the project's own `CLAUDE.md` when present. Project conventions supplement owner policy within the host's instruction hierarchy; they do not override it.
4. Only when no narrower user request is active: inspect the full Strata board, including every status, folded Open/Done sections, and dependencies. Prioritize ready approved tasks and advance them through the applicable [WORKFLOW.md](../../WORKFLOW.md) gates; move proposed work toward its required approvals without bypassing them. Make concrete progress rather than stopping at a status report.

If the user's message already names a specific task, treat steps 1-3 as the useful part of this sweep and skip the open-ended board triage in step 4 — act on what they asked for instead.

Before any Strata task, issue, document, or C4 operation, also read the canonical tool skill at `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md` and [STRATA_POLICY.md](../../STRATA_POLICY.md).

Read [WORKFLOW.md](../../WORKFLOW.md) for a new feature/system or implementation delivery, [TASK_CONTRACT.md](../../TASK_CONTRACT.md) when assigning work, [GITHUB_FLOW.md](../../GITHUB_FLOW.md) before any branch/PR/merge operation on a repo with a GitHub remote, and [MIGRATION.md](../../MIGRATION.md) only for maintenance/setup.

Delegated workers never run this sweep themselves: they follow their supplied task and selected role, do not read private memory, and do not expand their task from this file. Only the coordinator (main chat) runs this startup and then hands workers fresh, sanitized context.
