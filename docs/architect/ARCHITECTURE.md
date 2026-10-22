# Strata Architecture

For people who modify the Strata code. For usage see [README.md](../../README.md); for agents drawing the C4 map see [AGENT_C4.md](../AGENT_C4.md).

## 1. Overview

Strata is a local tool for managing the knowledge of multiple projects: tasks/issues, decisions, block-based pages, an HTML document index, C4 maps and an audit log. Everything lives in **a single SQLite file**.

Principles:

- **Write through audited services.** CLI/MCP and three scoped viewer routes use the shared service layer. `POST /api/c4/object` mutates objects; `/api/c4/port` mutates ports; `/api/c4/link` mutates connections; no route stores layout. Every route validates and writes the DB source of truth and audit row transactionally, with Host, Origin, JSON, and size checks. YAML is only an import/export format; it is not mutated by viewer edits.
- **Database is the source of truth.** C4 YAML is an import/export format; the viewer reads the DB. The renderer owns layout: no coordinates are stored.
- **No heavy dependencies.** Python stdlib + PyYAML; vanilla JS, no build, no CDN (third-party libraries live in `viewer/vendor/`).

```
 YAML / JSON / docs_dir ──► strata.py (CLI) ──► SQLite ◄── strata/server.py (GET + scoped C4 POST) ◄── browser (viewer/)
                                   │                                     ▲
                                   └──────── c4 context / flow ──► agent ┘ (compact text)
```

## 2. Directory layout

| Path | Role |
|---|---|
| `strata.py` | CLI entry point (argparse), calls into the modules in `strata/` |
| `strata/schema.sql` | The whole schema: tables, append-only triggers, FTS5 |
| `strata/db.py` | Connection, `init` + migrate, CRUD for project/doc/item/page/link, audit, `fold` for search |
| `strata/c4.py` | Read/validate YAML, load into the DB (upsert + delete what was dropped), `read_model`, issue detection, `context`, flow trace |
| `strata/roadmap.py` | Roadmap import, syncing steps/gates into items, phases/criteria, gate checks and audit |
| `strata/blocks.py` | Validates the 8 block types of a page |
| `strata/server.py` | HTTP server: static files, GET `/api/*`, four scoped C4 POST routes, `/docs/*`, `/code/*` |
| `viewer/app.html`, `app.js`, `app.css` | Multi-project app shell (sidebar, tabs, Ctrl+K, theme) |
| `viewer/index.html` | C4 viewer (zoom by level, flows, tags, object search) |
| `viewer/page.html`, `page.js`, `page.css` | Renders block-based pages |
| `viewer/roadmap.js`, `viewer/app.js` | Draws the roadmap block and the roadmap tab / task board |
| `viewer/vendor/` | `dagre` (layout), `mermaid` |
| `viewer/assets/` | Decorative SVGs for the top of the Overview page |
| `examples/` | Sample C4 models (`*.strata.yaml`), sample pages (`*.page.json`) |
| `scripts/` | Auxiliary tools (tracing the hero image to SVG), not part of the runtime |
| `tests/` | pytest, one file per module |

## 3. Data model

Every table (except `project`) has a `project` column; the primary key is usually `(project, id)`.

| Table | Content | Notes |
|---|---|---|
| `project` | id, name, root, docs_dir, parent | `parent` builds the project tree in the sidebar |
| `item` | task, issue, rule, knowledge, draft, note | `status`: proposed / approved / open / doing / done / rejected |
| `decision` | ADR: context, decision, consequences, rejected_options | **Append-only**: triggers block deletes and only allow changing `status`. `rejected_options` is required |
| `page` | slug, title, kind (research/discussion/note), `blocks` JSON | `text` is the extracted text used for search |
| `doc` | index of HTML files in `docs_dir` | `kind` follows the first folder, `status` = missing when the file disappears |
| `c4_meta` | model name, absolute `root`, layout, tag definitions | one row per project |
| `c4_object` | actor, system, app, store, component, group, file, function | `parent` builds the tree; `kind` stores a subtype; `links` point to code files |
| `c4_port` | typed input/output port attached to an object | id is unique within a project; optional JSON schema |
| `c4_connection` | from → to, kind (network/call/queue), status, interface, payload | may reference its source and target ports |
| `c4_interface` | callable contract of an object: http/function/queue/event | |
| `c4_flow` | JSON list of steps referencing connections or objects | |
| `c4_link` | links a C4 object with an item/decision | |
| `audit` | ts, tool, target, before, after | every write command adds a row |
| `search` | FTS5 over item, decision, page, doc | triggers keep it in sync |

**Vietnamese search.** The tokenizer `unicode61 remove_diacritics 2` strips diacritics, but `đ` cannot be decomposed, so the triggers convert `đ→d`; queries must go through `db.fold` to be converted the same way.

**Migration.** `db.init` runs `ALTER TABLE ADD COLUMN` according to the `ADDED` list. When a `CHECK` must change (SQLite cannot alter it), the old table is renamed to `*_old`, recreated, and the data copied over. To add a column: add it to `schema.sql` **and** `ADDED`.

Default DB: `$STRATA_DB`, otherwise `/home/abel/project/tools/strata/strata.db`. Every command accepts `--db FILE`.

## 4. C4 flow

1. **Read YAML** (`c4.read_yaml`): check keys against `KEYS`; interfaces nested in an object are split out.
2. **Validate**: type is in `TYPES`, parent valid per `PARENTS`, ids unique, connections/flows point to things that exist, kind/status valid.
3. **Load/export**: `import-yaml` upserts objects, ports, connections, interfaces and flows; `export-yaml` serializes the DB model. `root` is stored as an absolute path.
4. **Serve** (`/api/c4`): `read_model` + `issues_by_object` (`dead_link`, `no_link`, `no_desc`) + `links` + `open_issues`.
5. **Draw** (`viewer/index.html`): only the direct children of the zoomed object are drawn at a time; connections at deeper levels are "lifted" to link the two visible ancestors and merged if they share a direction. Layout uses dagre.

Valid parent–child tree:

| type | Level | Allowed parent |
|---|---|---|
| `actor`, `system` | L1 Context | top level, `group` |
| `app`, `store` | L2 Container | `system`, `group` |
| `component` | L3 Component | `app`, `group` |
| `file`, `function` | L4 Code | `component`, `file` |
| `group` | grouping | top level, `group`, `system`, `app` |

**For agents.** `c4 context` prints a compact tree with a token limit (estimated as `len/4`), trimming from the flows upward when exceeded. `c4 flow --id F` prints one line per step: `N. A → B [kind] text (interface) | payload: …`.

## 5. Server

`strata/server.py` uses the stdlib `http.server` with one shared SQLite connection guarded by a lock (`lock`).

Protections:

- **DNS rebinding block:** the `Host` header must be `127.0.0.1:PORT` or `localhost:PORT`, otherwise 403 is returned.
- **Path traversal block** on `/docs/`, `/code/`, `/vendor/`, `/assets/`: resolve, then check `is_relative_to(root)`.
- **Hide sensitive files:** dotfiles, `*.db`, `*.sqlite*` return 404.
- **Filter whitelist:** `/api/items`, `/api/query` only accept allowed columns/values, anything else returns 400.
- `/code/*` always returns `text/plain`.

Known limitation: HTML documents under `/docs/` are served from the same origin as the app and are not isolated. Only point `docs_dir` at documents you trust.

Pages refresh themselves: `page.js` polls `/api/page/<p>/<s>/version` every 2 seconds (`updated_at` + `PRAGMA data_version`).

## 6. Extending

### Roadmaps by phase

The source definition is `docs/plan/<roadmap>.yaml`. The `roadmap-<id>` page stores the plan content, and `blocks.def` stores phases, C4 blocks, and criteria. Steps and gates are items with `spec.roadmap` and `spec.step_key`, so steps use the standard item workflow for claiming, submitting, and approving work. `item_dep` links gates to their steps.

`strata/roadmap.py` validates definitions, C4 blocks, and criteria. Imports upsert existing records and retain omitted steps as orphans. If acceptance or verification details change after a step is done, the step becomes stale and requires user reacceptance. Criterion results are audited, `confirm_by` controls who can record them, and only the user can waive a criterion. A gate can pass only when its steps are done and all core criteria pass or have been waived by the user. `/api/roadmap` is read-only; the viewer renders its data without changing state.

See [Create and Run a Roadmap](../guide/roadmap.yaml) and [Task Board and Roadmap Viewer](../guide/viewer-roadmap.yaml).

- **New CLI command:** add a subparser in `strata.py`, put the logic in `strata/db.py` or `strata/c4.py`, and write `audit` if it writes.
- **New C4 field:** `KEYS` + validation in `c4.py`, a column in `schema.sql` + `ADDED` in `db.py`, the `INSERT … ON CONFLICT` statement on load, then the viewer.
- **New API:** hold `lock` when reading or writing the shared DB connection, and filter inputs with a whitelist. Viewer POSTs are limited to `/api/c4/object`, `/api/c4/port`, and `/api/c4/link`; layout is computed by the viewer and never stored; all use the service transaction and audit. Do not add a generic write route. Update CLAUDE.md rule #1 and section 1 if this allowlist changes.
- **Page blocks:** fixed at exactly 8 types; adding one requires agreement from the project owner first.

## 7. Running and testing

```
python3 strata.py init --db /tmp/x.db
python3 strata.py import-yaml examples/strata.strata.yaml --project strata --db /tmp/x.db
python3 strata.py serve --db /tmp/x.db                   # http://127.0.0.1:8740
python3 -m pytest -q
```

On the main machine the server runs as the systemd user unit `strata.service` on port 8740: after changing Python run `systemctl --user restart strata`; after changing CSS/JS just reload the page (Ctrl+Shift+R).
