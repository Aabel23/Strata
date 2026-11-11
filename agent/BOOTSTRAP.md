# Agent startup

Canonical governance lives in `/home/abel/project/tools/strata/agent/`. Resolve relative governance links and governance-file paths against that canonical agent directory, not the installed symlink directory or project working directory. Project-relative paths and tool-repository paths retain their stated bases; skill-local references resolve against their skill directory. Edit that source, never an installed copy. This entrypoint is loaded through `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.

Full governance startup — owner policy (HIEN_PHAP/COORDINATOR), private-memory recall (RAM.md/OPEN.md via Obsidian MCP), the project's own `CLAUDE.md`, and an open-ended Strata board triage — is **not automatic**. It runs only through the `agent-startup` skill (`skills/agent-startup/SKILL.md`); load it explicitly, or when the user asks to pick up pending/approved work with no narrower target. An ordinary scoped request (a fix, a question, a one-off edit) proceeds directly without it.

Delegated workers follow their supplied task and selected role. Do not read private memory or expand the task from this startup file. Coordinators must provide fresh, sanitized context.

Before any Strata task, issue, document, or C4 operation, read its canonical tool skill at `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md` and [STRATA_POLICY.md](STRATA_POLICY.md).

Read [WORKFLOW.md](WORKFLOW.md) for a new feature/system or implementation delivery, [TASK_CONTRACT.md](TASK_CONTRACT.md) when assigning work, [GITHUB_FLOW.md](GITHUB_FLOW.md) before any branch/PR/merge operation on a repo with a GitHub remote, and [MIGRATION.md](MIGRATION.md) only for maintenance/setup. Skills are loaded when their task applies.

For an approved implementation task in a GitHub-backed Strata project, load [strata-task-pipeline](skills/strata-task-pipeline/SKILL.md).

## Agent hooks

The hook sources are in `hooks/`. `scope_guard.py` checks coder edit scope; `ci_edit_guard.py` requires explicit task approval for CI workflow edits; `github_guard.py` blocks agent PR creation and destructive remote pushes; `subagent_event.py` reports native subagent starts/stops to the viewer. They run only once registered in machine-level Claude/Codex settings; project configuration does not register them. Register the supported host hooks with one idempotent command that preserves other entries (dry run without `--apply`):

```bash
python3 /home/abel/project/tools/strata/agent/scripts/install_hooks.py --apply
```

The scope hook treats an edit as a coder's when the process has `STRATA_AGENT_ROLE=coder` or the hook payload names subagent type `coder`; a coder needs the coordinator-generated `.strata-task-contract.json` marker described in `COORDINATOR.md`. Codex requires review and trust of new or changed non-managed hooks through `/hooks` before they run. These hooks prevent accidental tool calls; remote branch protection and scoped credentials remain necessary.
