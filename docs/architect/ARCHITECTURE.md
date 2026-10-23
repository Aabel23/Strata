# Strata Architecture

For people who modify the Strata code. For usage see [README.md](../../README.md); for agents drawing the C4 map see [AGENT_C4.md](../AGENT_C4.md).

## 1. Overview

Strata is a local tool for managing the knowledge of multiple projects: tasks/issues, block-based pages, an HTML document index, C4 maps and an audit log. Everything lives in **a single SQLite file**.

Principles:

- **Write through audited services.** CLI/MCP are the common write path. The one exception is `POST /api/c4/edit` (the Architect editor), the only write route in the server. It edits the YAML folder (`docs/c4`) through `strata/c4_edit.py` and re-imports it, so the folder stays the source of truth and each edit leaves a `c4-import` audit row. Everything else in the viewer and server is read-only.
- **Database is the source of truth.** C4 YAML is an import/export format; the viewer reads the DB. The renderer owns layout: no coordinates are stored.
- **No heavy dependencies.** Python stdlib + PyYAML; vanilla JS, no build, no CDN (third-party libraries live in `viewer/vendor/`).

```
 YAML / JSON / docs_dir ──► strata.py (CLI) ──► SQLite ◄── strata/server.py (GET + POST /api/c4/edit) ◄── browser (viewer/)
                                   │                                     ▲
                                   └──────── c4 context / flow ──► agent ┘ (compact text)
```

## 2. Directory layout

| Path | Role |
|---|---|
| `strata.py` | CLI entry point (argparse), calls into the modules in `strata/` |
| `strata/schema.sql` | The whole schema: tables, append-only triggers, FTS5 |
| `strata/db.py` | Connection, `init` + migrate, CRUD for project/doc/item/page/link, audit, `fold` for search |
| `strata/c4_layered.py` | The only C4 format (folder `map.yaml` + `contracts/` + `behavior/` + `flows/`): load, validate, import/export, `read_model`, `context`, flow trace, contract text, `write_model` (atomic write of a loaded model back to the folder) |
| `strata/roadmap.py` | Roadmap import, syncing steps/gates into items, phases/criteria, gate checks and audit |
| `strata/blocks.py` | Validates the 8 block types of a page |
| `strata/c4_edit.py` | Architect editor back end: `apply(c, project, op, yes)` runs one of six ops (`add_object`, `update_object`, `delete_object`, `add_link`, `update_link`, `delete_link`) on the C4 folder |
| `strata/server.py` | HTTP server: static files, GET `/api/*`, `/docs/*`, `/code/*`; the only write route is `POST /api/c4/edit` |
| `viewer/app.html`, `app.js`, `app.css` | Multi-project app shell (sidebar, tabs, Ctrl+K, theme) |
| `viewer/index.html` | C4 viewer (zoom by level, flows, tags, object search) |
| `viewer/page.html`, `page.js`, `page.css` | Renders block-based pages |
| `viewer/roadmap.js`, `viewer/app.js` | Draws the roadmap block and the roadmap tab / task board |
| `viewer/vendor/` | `dagre` (layout), `mermaid` |
| `viewer/assets/` | Decorative SVGs for the top of the Overview page |
| `examples/` | Sample pages (`*.page.json`) |
| `scripts/` | Auxiliary tools (tracing the hero image to SVG), not part of the runtime |
| `tests/` | pytest, one file per module |

## 3. Data model

Every table (except `project`) has a `project` column; the primary key is usually `(project, id)`.

| Table | Content | Notes |
|---|---|---|
| `project` | id, name, root, docs_dir, parent | `parent` builds the project tree in the sidebar |
| `item` | task, issue, rule, knowledge, draft, note | `status`: proposed / approved / open / doing / done / rejected |
| `page` | slug, title, kind (research/note), `blocks` JSON | `text` is the extracted text used for search |
| `doc` | index of HTML files in `docs_dir` | `kind` follows the first folder, `status` = missing when the file disappears |
| `c4_meta` | map name, absolute `root`, `source` (the imported folder) | one row per project with a map |
| `c4_object` | actor, system, app, store, component, group | `parent` builds the tree; `owns` lists code globs; `behavior` names a behavior module |
| `c4_connection` | a link: from → to, name, summary, status, `detail` (contract id) | |
| `c4_contract` | call detail of a link: transport, body, `start`/`end` code symbols | id is `<file>.<id>` |
| `c4_behavior` | states and transitions of one module | |
| `c4_flow` | JSON list of steps (`link` or `at`) | |
| `c4_link` | links a C4 object with an item | |
| `audit` | ts, tool, target, before, after | every write command adds a row |
| `search` | FTS5 over item, page, doc | triggers keep it in sync |

**Vietnamese search.** The tokenizer `unicode61 remove_diacritics 2` strips diacritics, but `đ` cannot be decomposed, so the triggers convert `đ→d`; queries must go through `db.fold` to be converted the same way.

**Migration.** `db.init` runs `ALTER TABLE ADD COLUMN` according to the `ADDED` list. When a `CHECK` must change (SQLite cannot alter it), the old table is renamed to `*_old`, recreated, and the data copied over. To add a column: add it to `schema.sql` **and** `ADDED`.

Default DB: `$STRATA_DB`, otherwise `/home/abel/project/tools/strata/strata.db`. Every command accepts `--db FILE`.

## 4. C4 flow

1. **Load** (`c4_layered.load`): read the folder, reject unknown keys.
2. **Validate** (`c4_layered.check`): kinds and status, parents, unique ids, link ends, `detail` and `behavior` targets, flow steps and continuity; contract symbols are checked against the Python AST (warnings).
3. **Import/export**: `c4 import` upserts objects, links, contracts, behavior and flows, deletes what the folder dropped and task links to objects that are gone, and writes an audit row; `c4 export` writes the folder back. `root` is stored as an absolute path.
4. **Serve** (`/api/c4`): `read_model` + `viewer_extra` (contracts, behavior) + `links` + `open_issues`; 404 when the project has no map.
5. **Draw** (`viewer/index.html`): only the direct children of the zoomed object are drawn at a time; links at deeper levels are "lifted" to join the two visible ancestors and merged if they share a direction. Layout uses dagre.

Valid parent–child tree:

| kind | Level | Allowed parent |
|---|---|---|
| `actor`, `system` | L1 Context | top level, `group` |
| `app`, `store` | L2 Container | `system`, `group` |
| `component` | L3 Component | `app`, `group` |
| `group` | grouping | any |

**For agents.** `c4 context` prints a compact tree with a token limit (estimated as `len/4`), trimming from the flows upward when exceeded. `c4 flow --id F` prints one line per step: `N. A → B [link name] text | key=value`, plus the contract's `start → end` under it.

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

### Architect editor (`POST /api/c4/edit`)

- **`strata/c4_edit.py` `apply`:** loads the project's C4 folder (from `c4_meta.source`), applies one op to a copy, then runs `c4_layered.check` on it. Errors that already existed before the edit are not blamed; only a finding that is new rejects the edit (`ValueError`, nothing written). If the edit would drop task links, it is refused unless `yes` is true (the viewer asks the user to confirm). It then writes the folder and runs `import_dir`; if the import fails, the previous model is written back and the error is re-raised. The result is `{ok, changed, warnings}` where warnings are only the new ones.
- **`c4_layered.write_model`:** writes a loaded model into the layered folder (`map.yaml`, `contracts/`, `behavior/`, `flows/`) with atomic writes and returns the changed paths.
- **Route guards, in order:** Host check (DNS rebinding), editing enabled, path, `X-Strata-Edit: 1` header, `Origin` (if sent) equal to `http://<Host>`, `Content-Type: application/json`, `Content-Length` present and at most 64 KB (`MAX_BODY`), body is a JSON object, optional boolean `yes`. Project comes from `?project=`, else the default project. Failures return 403/415/413/400; unknown project 404.
- **`allow_edit`:** `make_server(allow_edit=None)` enables the route only when the bind host is loopback. `strata.py serve --allow-edit` forces it on, `--no-edit` forces it off.
- **Not editable here:** contracts, flows, behavior, renaming an object id, changing a link's `from`/`to`. Use the files and `c4 import`.

## 6. Extending

### Roadmaps by phase

The source definition is `docs/plan/<roadmap>.yaml`. The `roadmap-<id>` page stores the plan content, and `blocks.def` stores phases, C4 blocks, and criteria. Steps and gates are items with `spec.roadmap` and `spec.step_key`, so steps use the standard item workflow for claiming, submitting, and approving work. `item_dep` links gates to their steps.

`strata/roadmap.py` validates definitions, C4 blocks, and criteria. Imports upsert existing records and retain omitted steps as orphans. If acceptance or verification details change after a step is done, the step becomes stale and requires user reacceptance. Criterion results are audited, `confirm_by` controls who can record them, and only the user can waive a criterion. A gate can pass only when its steps are done and all core criteria pass or have been waived by the user. `/api/roadmap` is read-only; the viewer renders its data without changing state.

See [Create and Run a Roadmap](../guide/roadmap.yaml) and [Task Board and Roadmap Viewer](../guide/viewer-roadmap.yaml).

- **New CLI command:** add a subparser in `strata.py`, put the logic in `strata/db.py` or `strata/c4_layered.py`, and write `audit` if it writes.
- **New C4 field:** `KEYS` + validation in `c4_layered.py`, a column in `schema.sql` + `ADDED` in `db.py`, `import_dir`/`export_dir`/`read_model`, then the viewer.
- **New API:** hold `lock` when reading or writing the shared DB connection, and filter inputs with a whitelist. The only write route is `POST /api/c4/edit`; for anything else, edit C4 in the folder and import with the CLI.
- **Page blocks:** fixed at exactly 8 types; adding one requires agreement from the project owner first.

## 7. Running and testing

```
python3 strata.py init --db /tmp/x.db
python3 strata.py c4 import docs/c4 --project strata --db /tmp/x.db
python3 strata.py serve --db /tmp/x.db                   # http://127.0.0.1:8740
python3 -m pytest -q
```

On the main machine the server runs as the systemd user unit `strata.service` on port 8740: after changing Python run `systemctl --user restart strata`; after changing CSS/JS just reload the page (Ctrl+Shift+R).
