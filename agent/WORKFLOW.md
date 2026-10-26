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
| 6 Review | Independent reviewer; Sonnet medium | Acceptance, scope and diff-focused security review; user approval closes the new-feature flow; resulting issues are recorded. |

Stage 5 uses the contract `code_map`; stage 6 compares `gitnexus detect-changes` with scope, both per [CODE_MAP.md](CODE_MAP.md). Explicit user model/effort requests override default profiles. Hosts select actual models; report unavailable mappings honestly. Existing fixes/refactors use their authorized task contract and mandatory independent review without manufacturing new-feature design gates.

Ticket states are approved → doing → review → done. The reviewer must differ from the owner. Only the main chat marks done after acceptance and required approvals.

Coder prompts start by loading `ponytail` at full level. Bugs within the approved specification may be fixed and noted. Coders/reviewers do not commit or run git state-changing commands (`stash`, `checkout`, `restore`, `reset`).

Reviewers inspect verification commands before running them. Rerun authorized required checks when safe in the approved environment; report evidence for every criterion. Without a sandbox, do not execute repository code: mark such verification `needs_validation`, never pass. Static inspection and deterministic parsing of configuration are allowed. Use `security-audit` guidance mode on the changed flow; a full six-phase audit requires a user request. Missing required skills/checks are disclosed, not silently waived.

Immediately after each task is done, the main chat makes a local commit of exactly its files, staging explicit paths, never `git add -A`. Message: `#N <task title>`. For parallel worktree tasks the main chat commits the task's files on its task branch the same way, then lands it with `agent/scripts/land.sh`. If a task file contains pre-existing uncommitted work, report the overlap to the user before committing. A local commit does not authorize push, publication or installation. Commit governance changes as well.

“Automatically finish flow X” authorizes stages 5–6 without repeated per-step questions; retain any still-unsatisfied explicit final approval. Do not silently change the approved design.
