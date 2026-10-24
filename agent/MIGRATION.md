# Agent governance ownership

Endo owns `BOOTSTRAP.md`, `HIEN_PHAP.md`, agent roles, hooks, and maintained skills in this directory. Change governance here. Strata is a tool; its canonical usage manual remains `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md`. Endo references that manual without copying it. Tool commands, data formats and server role permissions remain Strata documentation; workflow policy belongs to Endo.

The previous paths under `/home/abel/project/tools/strata/agent/` are compatibility symlinks to Endo for bootstrap, constitution, roles, hooks and maintained skills. They contain no duplicate rule text. Existing installed links in `~/.claude` and `~/.codex` can continue resolving through them; this migration does not modify those installations. New installations should link directly to Endo as described in this maintainer reference. Keep the compatibility links until all installations have been updated.

`skills/schematic` is an external clone, excluded from Strata's git repository. Its existing directory is preserved in place; Endo links to it rather than copying its dependency tree or treating it as maintained governance. External pack skills remain in `~/.claude/packs/`.

Both repositories must be available at their documented paths for compatibility links and the external skill link to resolve. Strata executable, database and format-document paths remain in the Strata repository.

## Layered refactor (2026-10-24)

Rationale and primary-source citations: [agent-system-prompts research](../docs/research/agent-system-prompts.yaml). This is the strict owner-compatible variant: it does not activate the report's optional direct-root coding, cross-module tasks, reduced approval/review, conditional-memory startup, or changed skill defaults. Evidence and instruction authority are now distinct; role instructions are not represented as access controls.

Loading map: BOOTSTRAP → shared HIEN_PHAP + coordinator; feature/delivery → WORKFLOW; delegation → TASK_CONTRACT; Strata operations → STRATA_POLICY plus Strata's canonical usage skill; research/session saving → the relevant maintained skill. Roles receive the relevant contract and policy, not private coordinator memory. Existing entrypoint, role, hook and skill paths remain compatible. Start a fresh session to reload changed installed rules; already-loaded text is not automatically replaced. No runtime sandbox or privacy isolation was added.

## User-owned setup

Maintainers do not change `~/.claude` or `~/.codex` as part of a repository refactor. The user manages installed links and host configuration. New links should point to Endo; retain old Strata compatibility links until all installations migrate.

```bash
mkdir -p ~/.claude/agents
ln -s /home/abel/project/tools/endo/agent/agents/*.md ~/.claude/agents/
claude mcp add --scope user strata -- python3 /home/abel/project/tools/strata/strata.py mcp --role main
codex mcp add strata -- python3 /home/abel/project/tools/strata/strata.py mcp --role main
```

The user approves project `.mcp.json` once in an interactive Claude session for the `strata-coder` and `strata-reviewer` servers. These commands are setup examples, not permission for an agent to run installation.

Owned skills belong in `agent/skills/<name>/SKILL.md`; the user links them into `~/.claude/skills/<name>` (and session-secondbrain into `~/.codex/skills/`). External packs (`ponytail`, `security-audit`, REA and electronics) retain their own locations/configuration; do not copy them here. Read the applicable pack documentation. `skills/schematic` remains an external clone/link; playwright-cli and dong-bo-laptop are outside this refactor.

Change rules in the relevant canonical layer, review independently and make the scoped local commit; do not append incident history to the shared core. Keep examples, model-routing experiments and citations in research/maintainer material. Host allowlists are host-specific: inspect actual dispatch/profile behavior, and use runtime restrictions for guarantees.
