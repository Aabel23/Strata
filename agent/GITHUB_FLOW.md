# GitHub flow

Applies to every project with a GitHub remote. `origin` is the source of truth. `main` is the default integration branch, protected on GitHub: PR required, required status checks, branch must be up to date before merge, linear history, no force-push or deletion, admins included. A project may configure a different PR integration base. Repos without a GitHub remote use `agent/scripts/land.sh` instead (local commit, local fast-forward, no push) — see "Local-only fallback". The operational skill is [strata-task-pipeline](skills/strata-task-pipeline/SKILL.md).

## Session start
- `git fetch origin main` before anything else that reads branch state. When the local `main` checkout is clean and no sibling task is active in that project, fast-forward it with `git pull --ff-only origin main`; leave a dirty or busy checkout untouched.

## Task start
- `git fetch origin main` again right before creating a branch or worktree.
- Branch from fresh `origin/main` only. Never base a task on a local-only or unpushed branch.
- Branch name: `<action>/<scope>/<work>_t<N>` (N = Strata task id). Action is `feat|fix|refactor|docs|test|chore`; scope comes from `spec.scope.module` or the project id for legacy tasks; work is a short task slug. Explicit `spec.action` wins; otherwise an issue is `fix` and a task is `feat`.
- New worktree per task at `<project parent>/.strata-worktrees/<project>/<branch>`, created from that fresh `origin/main`. Its relative folder name is exactly the branch name. Retry uses the same branch and folder.

## During work
- Push the task branch at every coder hand-back and after every fix. Nothing important stays local-only.
- A supervised task agent may commit inside its assigned worktree; the runner checks and pushes. For other delegated workers the coordinator commits exact scoped paths (never `git add -A`) and pushes. Reviewers never mutate Git state.
- Fixups during review are additional commits on the task branch, not amends.
- Refresh `origin/main` before final review and merge. If it advanced, rebase the task branch, rerun checks, and push the new head for CI to verify.

## Submit
- The owner-provided CI bot runs checks on every pushed task branch and creates or updates one PR only after that head passes. Agents never create PRs. Until the CI bot exists or succeeds, the task is awaiting PR; do not create one manually as a workaround.
- PR title: `#N <task title>`.
- PR body or linked status artifact: Strata task, latest head SHA, acceptance evidence, verification commands and results (exact counts), risks, rollback, explicitly unverified items.
- Avoid stacked PRs: land dependencies first. If stacking is unavoidable, base on the dependency branch and retarget onto `main` after it merges.

## Review
- Independent reviewer required, distinct from the task owner (per WORKFLOW.md).
- CI workflow changes require both an approved task with `ci_change_approved: true` and `.github/workflows` in `scope.touch`, then independent review like code.

## CI rules (hard gate)
- Every required check must be green on the latest head. Skipped, didn't-run, or "incomplete" is a failure, never a pass.
- CI must actually execute the project's tests (unit, integration, end-to-end where defined) with exact counts in logs/artifacts, and fail on unexpected skips.
- Never disable, weaken, or skip-mark a test to get green. A flaky test gets a Strata issue and a fix.
- Every module/feature should have tests wired into CI; missing coverage is tracked as Strata tasks.

## Merge
The coordinator squash-merges a task PR, with no further user question, when ALL hold:
1. Required checks green on the latest head.
2. Independent reviewer ACCEPT recorded.
3. Branch up to date with `main`.
4. The Strata task's acceptance criteria met.

Squash commit message: `#N <task title>` plus the co-author trailer.

## After merge
- Remove the local worktree.
- Mark the Strata task done with the PR URL and merge SHA.
- Fast-forward local `main` when its checkout is clean. Leave the remote task branch in place; agents do not delete remote branches.

## Reverts and hotfixes
Reverts go through a revert PR under these same rules. Hotfixes use the same flow, with priority.

## Authorization table
| Action | Authorization |
|---|---|
| Push task branches | Standing — no per-action question |
| Open/update/mark-ready PRs | CI bot only, after checks on the exact pushed head; no agent authorization |
| Squash-merge per the Merge rule above | Standing — no per-action question |
| Delete remote branches, merged or unmerged | Owner only; agents have no standing authorization |
| Close superseded PRs (with a note linking the replacement) | Owner or CI bot only |
| Force-push to `main` or shared branches | Explicit user approval required |
| History rewrites on shared branches | Explicit user approval required |
| Releases, tags, deployments, publishing | Explicit user approval required |
| Repository settings changes | Explicit user approval required |
| Installing software on the user's machine | Explicit user approval required |
| Anything touching production data or secrets | Explicit user approval required |

## Local-only fallback
Repositories without a GitHub remote keep the existing local-commit flow: `agent/scripts/land.sh`, local fast-forward onto `main`, no push.
