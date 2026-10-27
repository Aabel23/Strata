# Gated delivery workflow

For a new feature or system, preserve these owner approval gates. Do not restart approved stages when the user authorizes continuation of the same scope.

| Stage | Work and default profile | Output and approval |
|---|---|---|
| 1 Discuss | Main chat | System blocks, responsibilities and tradeoffs; user approves. |
| 2 Diagram | Delegated Sonnet medium | Project C4 objects/flow following `docs/AGENT_C4.md`; validate/import through Strata; user approves. |
| 3 Research | `skills/research-stage/SKILL.md`; Sonnet medium | Research YAML and open decisions; user decides each consequential question. |
| 3b Dissect | Only when requested; Opus low | Shipped artifacts use REA; open repositories use source reading; user approves. |
| 4 Tasks | Main chat or general-purpose tasker; Sonnet low | One-module tickets, measurable acceptance, verify, dependencies and interfaces; user approves before task creation. |
| 5 Implement | Coder; Sonnet medium | Small changes with ticket verification; complete approved scope without asking again. |
| 6 Review | Independent reviewer; Sonnet medium | Acceptance, scope and diff-focused security review; each task PR then merges under GITHUB_FLOW.md (GitHub repos) or land.sh after review (local-only); user approval of the delivered feature closes the new-feature flow; resulting issues are recorded. |

Stage 5 uses the contract `code_map`; stage 6 compares `gitnexus detect-changes` with scope, both per [CODE_MAP.md](CODE_MAP.md). Explicit user model/effort requests override default profiles. Hosts select actual models; report unavailable mappings honestly. Existing fixes/refactors use their authorized task contract and mandatory independent review without manufacturing new-feature design gates.

For implement coders, the coordinator provisions the root `.strata-task-contract.json` marker in each task worktree. Its `scope.touch` list must be copied from the accepted task contract, and `STRATA_AGENT_ROLE=coder` must be present in the coder process environment. The PreToolUse hook in `hooks/scope_guard.py` then fails closed on missing/malformed contract scope and blocks Edit/Write-family tools outside those paths. See [COORDINATOR.md](COORDINATOR.md) for the marker schema and limits. Project source contains the hook implementation, but host registration is separate machine configuration.

Ticket states are approved → doing → review → done. The reviewer must differ from the owner. Only the main chat marks done after acceptance and required approvals; for a repo with a GitHub remote, "done" means merged to `main` (see [GITHUB_FLOW.md](GITHUB_FLOW.md)), for a local-only repo it means landed via `agent/scripts/land.sh`.

Coder prompts start by loading `ponytail` at full level. Bugs within the approved specification may be fixed and noted. Coders/reviewers do not commit or run git state-changing commands (`stash`, `checkout`, `restore`, `reset`).

Reviewers inspect verification commands before running them. Rerun authorized required checks when safe in the approved environment; report evidence for every criterion. Without a sandbox, do not execute repository code: mark such verification `needs_validation`, never pass. Static inspection and deterministic parsing of configuration are allowed. Use `security-audit` guidance mode on the changed flow; a full six-phase audit requires a user request. Missing required skills/checks are disclosed, not silently waived.

Immediately after each task's files change, the main chat commits exactly those files, staging explicit paths, never `git add -A`. Message: `#N <task title>`. Landing itself follows [GITHUB_FLOW.md](GITHUB_FLOW.md) for a repo with a GitHub remote (branch, PR, CI, review, squash merge), or `agent/scripts/land.sh` for a local-only repo. If a task file contains pre-existing uncommitted work, report the overlap to the user before committing. Commit governance changes as well.

“Automatically finish flow X” authorizes stages 5–6 without repeated per-step questions; retain any still-unsatisfied explicit final approval. Do not silently change the approved design.
