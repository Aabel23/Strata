# CI bot contract

The owner will provide the CI implementation. The task pipeline depends on this interface; it does not install a workflow or grant agents PR permissions.

- Trigger on a push to a task branch matching `action/scope/work_t<ID>`. Ignore `main` and unrelated branches.
- Run the project's required checks on the pushed head SHA. A skip, cancellation, or incomplete check is not a pass. Record exact commands and counts.
- Only after checks pass, create or update one PR for that head into the project's configured integration branch (`main` for Strata). Use an idempotency key based on repository, head branch, and base branch; reruns update the same PR.
- Put the Strata task id, head SHA, check evidence, and branch in the PR body or a machine-readable status artifact. The task id comes from the `_t<ID>` suffix and is verified against the Strata task record before automation acts.
- On a later push, invalidate earlier check evidence; the PR reflects the latest head. CI never auto-merges merely because checks pass. An independent reviewer and the merge gate remain separate.
- Use a dedicated CI identity with only the permissions required to read code and create/update PRs. It cannot delete branches, bypass branch protection, or change CI and repository settings. Protect `main` server-side and require checks at the merge point.
- If CI or PR creation fails, leave the branch and task intact and report the exact failure. Never let an agent create a replacement PR to hide the failure.
