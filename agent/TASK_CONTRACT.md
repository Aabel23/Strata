# Task and handoff contract

Use a short structured message for small tasks. Include these facts; do not invent runtime fields the host cannot establish:

```yaml
task_id: <ticket or stable reference>
mode: implement # research or review
original_intent: <user outcome and material constraints>
goal: <one bounded deliverable>
acceptance: [<observable conditions and expected evidence>]
binding_decisions: [<approved requirements>]
open_to_challenge: [<proposals, if any>]
base: <for a repo with a GitHub remote, the origin/main SHA the task branch forked from; otherwise a commit/tree or described snapshot; identify existing dirty inputs>
branch: <task/<N>-<short-slug>, for GitHub repos>
pr: <PR URL once opened, else n/a>
scope:
  module: <one module>
  read: [<relevant files/interfaces>]
  touch: [<authorized write paths; empty for read-only roles>]
  forbid: [<excluded paths/actions>]
dependencies: [<preceding tasks and interface contracts>]
open_questions: []
context: [<repository/source references; never private memory>]
code_map: <GitNexus evidence (not instructions) per CODE_MAP.md with index commit, or n/a (docs-only), or unavailable (<reason>)>
verify:
  - procedure: <exact command or manual check>
    environment: <authorized sandbox and prerequisites>
    side_effects: <writes/network/services>
authorization: <already-approved actions; no implicit commit, publish, or delegation. For GitHub repos, GITHUB_FLOW.md's standing authorization already covers pushing this task branch, opening/updating/marking its PR ready, and its eventual squash-merge and branch deletion>
return: <candidate identity, files/findings, acceptance evidence, checks and limitations>
```

An authorization field documents permission; it cannot grant unavailable capabilities. Include a budget only if explicitly supplied. Stop for a concrete scope/design conflict, continue independent work, and return a resumable handoff.

The reviewer receives original intent, contract, base/candidate identity, diff and factual test evidence. Do not hide essential assumptions or migration facts. Return pass/fail/not_verified per acceptance criterion and accept/rework/needs_validation overall. Evidence belongs to the exact candidate reviewed.
