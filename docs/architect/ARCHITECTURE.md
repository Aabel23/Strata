# Strata Architecture

For people who modify the Strata code. For usage see [README.md](../../README.md); for agents drawing the C4 map see [AGENT_C4.md](../AGENT_C4.md).

## 1. Overview

Strata is a local tool for managing the knowledge of multiple projects: tasks/issues, block-based pages, an HTML document index, C4 maps and an audit log. Everything lives in **a single SQLite file**.

Principles:

- **Write through audited services.** CLI/MCP are the common write path. The server has exactly three write routes, all guarded (see *UI write routes*): `POST /api/c4/edit` (the Architect editor) edits the YAML folder (`docs/c4`) through `strata/c4_edit.py` and re-imports it, so the folder stays the source of truth and each edit leaves a `c4-import` audit row; `POST /api/item` edits tasks/issues and `POST /api/project` adds, edits or deletes projects, both through `strata/service.py` with an audit row. Everything else in the viewer and server is read-only.
- **Database is the source of truth.** C4 YAML is an import/export format; the viewer reads the DB. The renderer owns layout: no coordinates are stored.
- **No heavy dependencies.** Python stdlib + PyYAML; vanilla JS, no build, no CDN (third-party libraries live in `viewer/vendor/`).

```
 YAML / JSON / docs_dir ──► strata.py (CLI) ──► SQLite ◄── strata/server.py (GET + 3 guarded POST routes) ◄── browser (viewer/)
                                   │                                     ▲
                                   └──────── c4 context / flow ──► agent ┘ (compact text)
```

## 2. Directory layout

| Path | Role |
|---|---|
| `strata.py` | CLI entry point (argparse), calls into the modules in `strata/` |
| `strata/schema.sql` | The whole schema: tables, append-only triggers, FTS5 |
| `strata/db/` | Package: connection, init + migrate, repository CRUD for project/doc/item/page/link/search, audit |
| `strata/c4_layered.py` | The only C4 format (folder `map.yaml` + `contracts/` + `behavior/` + `flows/`): load, validate, import/export, `read_model`, `context`, flow trace, contract text, `write_model` (atomic write of a loaded model back to the folder) |
| `strata/blocks.py` | Validates the 8 block types of a page |
| `strata/c4_edit.py` | Architect editor back end: `apply(c, project, op, yes)` runs one of six ops (`add_object`, `update_object`, `delete_object`, `add_link`, `update_link`, `delete_link`) on the C4 folder |
| `strata/server.py` | HTTP server: static files, GET `/api/*`, `/docs/*`, `/code/*`; the write routes are `POST /api/c4/edit`, `POST /api/item`, `POST /api/project` |
| `viewer/app.html`, `app.js`, `app.css` | Multi-project app shell (sidebar, tabs, Ctrl+K, theme) |
| `viewer/index.html` | C4 viewer (zoom by level, flows, tags, object search) |
| `viewer/page.html`, `page.js`, `page.css` | Renders block-based pages |
| `viewer/app.js` | App shell, overview, task board |
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

### UI write routes (`POST /api/item`, `POST /api/project`)

- **`POST /api/item {op, ...}`:** `add` (`service.add_item`), `edit` (`service.edit_item`: title, body, status, priority, spec goal/acceptance/verify/scope), `delete` (`service.delete_item`), `dep_add` / `dep_rm` (dependencies). Project comes from `?project=` or the body. Hard delete: the row and its dependency edges are removed and an audit row records what was deleted.
- **`POST /api/project {op, ...}`:** `add`, `edit` (`service.edit_project`: name, root, docs_dir, parent, description), `delete` (`service.delete_project`). Delete is a hard delete of the project's DB rows only (files untouched). It needs `confirm` equal to the project id (typed in the UI) and first writes an automatic DB backup into `backups/`; no backup, no delete.
- **Guards on every write route, in order:** Host check, editing enabled (`allow_edit`), path, per-start token in header `X-Strata-Token` (random, generated when the server starts, so a restart invalidates old pages until reload), `Origin` (if sent) equal to `http://<Host>`, JSON content type, body size cap, JSON object body. Failures return 403/415/413/400; `ValueError` maps to 400, `KeyError` to 404, anything else to a generic 500.
- **Error model:** a failed op rolls back the transaction; nothing is half written.

### Code layer (read-only)

The Code level below components is derived data; nothing is stored in the C4 YAML.

- **`c4_layered.component_files(c, project, object_id)`:** expands the object's `owns` globs under the project root and returns `{object, root, files, missing, truncated}` (code files only, capped at `FILE_CAP` = 2000). `KeyError` for an unknown project or object.
- **`symbols.file_outline(c, project, root, rel)`:** returns `{path, loc, symbols, error}` for one file; Python only, classes and methods. `ValueError` outside root, `FileNotFoundError` if missing.
- **`symbols.source_of(c, project, root, sid, ctx=0)`:** returns `{id, path, start, end, text, cut}` for a symbol id `path::Qual.name`, capped at 200 lines (`CAP`).
- **Routes (all GET):** `/api/code/files?project=&object=`, `/api/code/symbols?project=&path=`, `/api/code/src?project=&id=`. Missing params 400, unknown object/symbol/file 404. The server opens the symbol cache `strata.symbols.db` lazily on the first call; it is derived data, refreshed lazily from the files (rebuildable, never authoritative).
- **Panel:** `viewer/index.html` (Code tab in the info pane, opened by the Code button or double-click on a childless component; deep link `#<object>/code/<path>::<Qual>`). Server text is inserted with `textContent`.
- **No write route was added** by the Code layer; all its routes are GET.

## 6. Extending

- **New CLI command:** add a subparser in `strata.py`, put the logic in `strata/db/` or `strata/c4_layered.py`, and write `audit` if it writes.
- **New C4 field:** `KEYS` + validation in `c4_layered.py`, a column in `schema.sql` + `ADDED` in `strata/db/`, `import_dir`/`export_dir`/`read_model`, then the viewer.
- **New API:** hold `lock` when reading or writing the shared DB connection, and filter inputs with a whitelist. The write routes are `POST /api/c4/edit`, `POST /api/item` and `POST /api/project`; a new one needs the same guards and an audited service function. For anything else, edit C4 in the folder and import with the CLI.
- **Page blocks:** fixed at exactly 8 types; adding one requires agreement from the project owner first.

## 7. Running and testing

```
python3 strata.py init --db /tmp/x.db
python3 strata.py c4 import docs/c4 --project strata --db /tmp/x.db
python3 strata.py serve --db /tmp/x.db                   # http://127.0.0.1:8740
python3 -m pytest -q
```

On the main machine the server runs as the systemd user unit `strata.service` on port 8740: after changing Python run `systemctl --user restart strata`; after changing CSS/JS just reload the page (Ctrl+Shift+R).
