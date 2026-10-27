# GitHub flow

Applies to every project with a GitHub remote. `origin` is the source of truth. `main` is the integration branch, protected on GitHub: PR required, required status checks, branch must be up to date before merge, linear history, no force-push or deletion, admins included. Repos without a GitHub remote use `agent/scripts/land.sh` instead (local commit, local fast-forward, no push) — see "Local-only fallback".

## Session start
- `git fetch` before anything else that reads branch state.

## Task start
- `git fetch` again right before creating a branch or worktree.
- Branch from fresh `origin/main` only. Never base a task on a local-only or unpushed branch.
- Branch name: `task/<N>-<short-slug>` (N = Strata task id).
- New worktree per task, created from that fresh `origin/main`.

## During work
- Push the task branch at every coder hand-back and after every fix. Nothing important stays local-only.
- Coders and reviewers never commit, push, or run git state-changing commands. The coordinator commits exact scoped paths (never `git add -A`) and pushes.
- Fixups during review are additional commits on the task branch, not amends.
- Rebase onto current `origin/main` before review and before merge.

## Submit
- Open a draft PR as soon as the first commit is pushed. Mark ready when submitted for review.
- PR title: `#N <task title>`.
- PR body: link to the Strata task; acceptance checklist with evidence per criterion; verification commands and results (exact counts); risks; rollback; explicitly unverified items.
- Avoid stacked PRs: land dependencies first. If stacking is unavoidable, base on the dependency branch and retarget onto `main` after it merges.

## Review
- Independent reviewer required, distinct from the task owner (per WORKFLOW.md).
- CI workflow changes are reviewed like code.

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
- Delete the remote task branch.
- Remove the local worktree.
- Mark the Strata task done with the PR URL and merge SHA.
- `git pull` main locally.

## Reverts and hotfixes
Reverts go through a revert PR under these same rules. Hotfixes use the same flow, with priority.

## Authorization table
| Action | Authorization |
|---|---|
| Push task branches | Standing — no per-action question |
| Open/update/mark-ready PRs | Standing — no per-action question |
| Squash-merge per the Merge rule above | Standing — no per-action question |
| Delete merged task branches | Standing — no per-action question |
| Close superseded PRs (with a note linking the replacement) | Standing — no per-action question |
| Force-push to `main` or shared branches | Explicit user approval required |
| Deleting unmerged remote branches | Explicit user approval required |
| History rewrites on shared branches | Explicit user approval required |
| Releases, tags, deployments, publishing | Explicit user approval required |
| Repository settings changes | Explicit user approval required |
| Installing software on the user's machine | Explicit user approval required |
| Anything touching production data or secrets | Explicit user approval required |

## Local-only fallback
Repositories without a GitHub remote keep the existing local-commit flow: `agent/scripts/land.sh`, local fast-forward onto `main`, no push.
