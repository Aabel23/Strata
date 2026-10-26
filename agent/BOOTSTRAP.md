# Agent startup

Canonical governance lives in `/home/abel/project/tools/strata/agent/`. Resolve relative governance links and governance-file paths against that canonical agent directory, not the installed symlink directory or project working directory. Project-relative paths and tool-repository paths retain their stated bases; skill-local references resolve against their skill directory. Edit that source, never an installed copy. This entrypoint is loaded through `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.

For the main chat:
1. Read [HIEN_PHAP.md](HIEN_PHAP.md) and [COORDINATOR.md](COORDINATOR.md).
2. Read `RAM.md` and `OPEN.md` in `/home/abel/.secondbrain` only through Obsidian MCP, using vault-relative paths. If unavailable, tell the user and continue from repository evidence.
3. Read the project's `CLAUDE.md` when present. Project conventions supplement owner policy within the host's instruction hierarchy.
4. When no narrower user request is active, inspect the full Strata board at startup, including every status, folded Open/Done sections, and dependencies. Prioritize ready approved tasks and advance them through the applicable [WORKFLOW.md](WORKFLOW.md) gates; move proposed work toward its required approvals without bypassing them. Make concrete progress rather than stopping at a status report.

Delegated workers follow their supplied task and selected role. Do not read private memory or expand the task from this startup file. Coordinators must provide fresh, sanitized context.

Before any Strata task, issue, document, or C4 operation, read its canonical tool skill at `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md` and [STRATA_POLICY.md](STRATA_POLICY.md).

Read [WORKFLOW.md](WORKFLOW.md) for a new feature/system or implementation delivery, [TASK_CONTRACT.md](TASK_CONTRACT.md) when assigning work, and [MIGRATION.md](MIGRATION.md) only for maintenance/setup. Skills are loaded when their task applies.

## Edit scope hook

The hook source is `hooks/scope_guard.py` in this repository. It is not registered by this file or by project configuration: the inspected Claude user settings currently register only the private-memory hook, so activating the scope guard requires a separate change to machine-level hook settings (and equivalent Codex host configuration where supported). Add this command to the existing `PreToolUse` hook list, preserving other entries:

```json
{
  "type": "command",
  "command": "python3 /home/abel/project/tools/strata/agent/hooks/scope_guard.py"
}
```

Coder launches must also provide `STRATA_AGENT_ROLE=coder` and a coordinator-generated `.strata-task-contract.json` marker as described in `COORDINATOR.md`; without host registration, the source hook does not run.
