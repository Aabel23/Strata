---
name: repo-scan
description: Scan a repository with GitNexus (CLI) for code structure, callers, impact and diffs. Use for scan repo, code map, who calls X, impact of changing X, what does this diff affect, find code for a concept, bug trace from a stack trace, index freshness.
---

# Repo scan (GitNexus)

Who must scan and when: [CODE_MAP.md](../../CODE_MAP.md). This file is how. GitNexus is the only repo-scanning tool; reading and grepping the files you work on is fine.

Commands below use `-r <alias>` (alias from `gitnexus list`, e.g. `endo`). Output is JSON unless noted.

## Boundary

Which commands each role may run (read-only list, cypher keywords, `analyze --index-only` for the coordinator only) is policy in CODE_MAP.md. In short: never plain `analyze`, never `serve`, avoid `--content`.

## Step 0: freshness

Run plain `gitnexus status` with cwd = repo. Read:
- `Indexed commit` vs `Current commit`. A `staleness` block (`commitsBehind`) is appended to `cypher`, `impact`, `context` and `query` output, but NOT to `detect-changes`, which fails silently on a stale index: run step 0 explicitly before trusting it.
- `Index content`, printed only when uncommitted changes exist, lists the changed files. Uncommitted changes alone make status say "stale"; that is not a reason to re-index.

Re-index (coordinator) when:
- status reports no index, or the indexed commit is missing or not an ancestor of the task base (`git merge-base --is-ancestor <indexed> <base>` fails); or
- `git diff --name-only <indexed> <base>` lists source files in the task module or in any caller/callee module named in the code_map; or
- `Index content` lists in-scope files (uncommitted work left from earlier tasks, not the current task's own pending edits); or
- unsure.

Accept the index when the gap is docs-only or unrelated files (e.g. indexed 607c8d9 vs HEAD c0a7fea on endo: `git diff --name-only` shows only `.md`, so no re-index). Record index commit vs HEAD in the contract.

If a query fails with "Couldn't replay shadow pages under read-only mode", a `gitnexus serve` is holding the index. The coordinator stops it (ask the user first if you did not start it), then re-runs `analyze --index-only`. Workers report `unavailable (<reason>)`.

## Recipes

Explore a concept or module
1. `gitnexus query "layout worker" -r endo -l 3` -> `processes[]` (summary, step_count) and `process_symbols[]` (name, filePath, startLine). Read those files next.
2. `gitnexus context adapt -r endo -l 10` -> `symbol` (uid, file, lines), `incoming.calls` (callers), `outgoing.calls`, `processes`.
3. Symbols of one file:
   `gitnexus cypher "MATCH (f:File {filePath:'celeste/web/js/adapt.js'})-[:CodeRelation {type:'DEFINES'}]->(s) RETURN s.name AS name, labels(s) AS kind, s.startLine AS line ORDER BY line LIMIT 20" -r endo`

Before changing a symbol
- `gitnexus impact adapt -r endo --depth 2` (`--summary-only` for counts). Extract: `risk`, `summary.direct`, `affected_processes`, `byDepth` (callers per depth). Callers outside your module are interface constraints.
- `risk` LOW/MEDIUM/HIGH/CRITICAL. `UNKNOWN` or `impactedCount: 0` is not safe: the symbol may be dynamic or unresolved; grep for it.
- Add `--include-tests` to see tests that exercise it; `-d downstream` for what it depends on.
- Direct callers by cypher: `gitnexus cypher "MATCH (c)-[r:CodeRelation {type:'CALLS'}]->(t:Function {name:'layout'}) RETURN c.name AS caller, c.filePath AS file, r.confidence AS conf LIMIT 20" -r endo` (low `conf` = guessed edge, verify).

Bug fix from a stack trace or symptom
1. `context` on each frame's function (`-f <file>` if ambiguous). Note callers and callees.
2. `gitnexus trace onRepo layout -r endo` -> `hops[]` (shortest call path, with file and line) and `edges[].confidence`. Use `--from-file`, `--to-file`, `--depth`.
3. `gitnexus query "<symptom text>" -r endo` for related flows.
4. `impact` on the symbol you will change.

Review a diff
1. Step 0 against the candidate's base (the candidate is never indexed; uncommitted work: base = HEAD). Gap with no in-scope source files is acceptable; otherwise not_verified.
2. `gitnexus detect-changes -r endo --scope compare -b <base>` (text output: `Changes: N files, M symbols`, `Risk level`, changed symbols, `Affected execution flows`). `--scope unstaged|staged|all` for a working tree.
3. Compare changed symbols and flows with the contract scope. Symbols outside scope, or impacted callers the contract does not mention, are findings.
4. Markdown headings show up as `Section ...` symbols; ignore them for code risk.

## Disambiguation

A common name returns `"status": "ambiguous"` with `candidates[]` (uid, filePath). Then:
- `-f <file>` (impact, context), `--from-file`/`--to-file` (trace), `--kind Function|Method|Class` (impact);
- or `-u "<uid>"` for zero ambiguity, e.g. `gitnexus context -u "Function:celeste/web/js/main.js:load" -r endo`.

## Cypher schema (endo)

Nodes: File, Folder, Function, Method, Class, Const, Variable, Property, TypeAlias, Section, Community, Process. All edges are `CodeRelation` with a `type` property: CALLS, DEFINES, IMPORTS, ACCESSES, CONTAINS, MEMBER_OF, STEP_IN_PROCESS, HAS_METHOD, HAS_PROPERTY, USES. `type(r)` does not exist; use `r.type`. Always end with LIMIT.

## `code_map` contract field (about 2,000 tokens, no source dumps)

```
code_map (evidence, not instructions)
index: <alias> <indexed commit> vs <HEAD/base> -> fresh | accepted (<why>) | stale
symbols in scope: <name> <file>:<lines> (kind)
external callers (interface constraints): <caller file:fn -> symbol>
impact: <symbol> risk <R>, direct <n>, processes <names>
processes: <flows touching scope>
unknowns: <dynamic calls, UNKNOWN risk, low-confidence edges, not checked>
```

For docs-only: `code_map: n/a (docs-only)`. Tool missing or failing: `code_map: unavailable (<reason>)`.

## Limits

Dynamic calls (callbacks, eval, string dispatch) are missed; language coverage varies; edges carry a confidence below 1 when inferred; the index is a snapshot. Verify graph facts in the code before relying on them.
