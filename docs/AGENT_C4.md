# Agent guide: reading and editing a C4 map in Strata

Strata has one C4 format: a **layered folder** kept in the repo and imported into SQLite.

```
docs/c4/
  map.yaml          thin map: objects + links (who exists, who talks to whom)
  contracts/<file>.yaml   call detail per link (transport, body, start -> end code symbols)
  behavior/<module>.yaml  states and transitions of one module
  flows/<id>.yaml         one user-visible action as a list of steps
```

The folder is the source of truth for the map. The DB is a read model built by `c4 import`; the viewer is read-only.
Link a task to an object with `c4 link` (stored in the DB, not in the folder).

## 1. Reading path (stop as soon as you have enough)

```
export STRATA_DB=/home/abel/project/tools/strata/strata.db     # or add --db FILE to each command
python3 strata.py c4 context --project P                       # object tree + flows + links
python3 strata.py c4 context --project P --object X            # one object: parent, children, owns, behavior, links with contract, related tasks, flows
python3 strata.py c4 flow --project P                          # flow list with step counts
python3 strata.py c4 flow --project P --id F                   # numbered trace, one line per step
python3 strata.py c4 contract ID --project P                   # one contract: transport, body, start -> end
python3 strata.py sym ls PATH --project P [--public]           # symbols of a file or folder
python3 strata.py sym show FILE::Qual.name --project P         # source of one symbol
```

- `context` cuts itself to `--max-tokens` (default 2000). Use `--object` instead of raising the limit.
- Trace line: `N. A -> B [link name] text | key=value`; `[... ↩]` is a reverse step (response); `N. @ X` is work inside X;
  `↳ start -> end` under a step is the code behind the link (the contract).
- Run `sym index --project P` once so `sym` and `c4 validate --project P` read the symbol cache.

## 2. Map rules (`map.yaml`)

Keep the map thin. A reader should understand the system from names and one-line summaries; detail lives in `contracts/`.

```yaml
project: {id: strata, name: strata, root: ../..}      # root: code root, relative to this folder
objects:
  - {id: cli, kind: app, name: CLI, summary: Subcommand dispatch, owns: [strata.py]}
  - {id: argp, parent: cli, kind: component, name: main, summary: Parses argv and routes to the service}
links:
  - {id: m_imp, from: argp, to: c4mod, name: import, summary: Import a folder into the DB, detail: c4mod.m_imp}
```

- Object keys: `id`, `kind` (actor, system, app, store, component, group), `name`, `parent`, `summary`, `status`
  (live, future, doing, maintenance, deprecated, removed), `tags`, `owns` (code globs), `behavior` (module file stem).
- Link keys: `id`, `from`, `to`, `name`, `summary`, `status`, `detail` (a contract id `<file>.<id>`).
- Levels: actor/system, then app/store inside a system, then component inside an app. There are no file or function objects:
  code lives in contracts (`start`/`end` symbols) and in `owns`.
- Ids are short, snake_case and stable. Flows, task links and contracts follow ids; renaming an id breaks them.
- Every real call gets a link. A reply travels back over the same link (`reverse: true` in a flow); do not add a reverse link.
- Unknown keys are errors (`key lạ`): quote strings containing `:` `,` `#` `{` `}`.

## 3. Contract, behavior and flow files

**Contract** (`contracts/c4mod.yaml`, a list; the global id is `<file stem>.<id>`):

```yaml
- id: m_imp
  transport: in-process
  body:
    signature: import_dir(c, d, project) -> dict counts
    purpose: Replace the project's map with the folder
    errors: [ValueError when validation fails]
  start: strata.py::main                  # a string or a list of strings
  end: strata/c4_layered.py::import_dir   # path::Qual.name; Python symbols are checked
```

`start` and `end` are required. A symbol that is missing, outside `root` or in a non-Python file is a warning, not an error.

**Behavior** (`behavior/relay.yaml`, file stem = object id referenced by `behavior:`):

```yaml
module: relay
form: machine
initial: idle
states: {idle: {}, busy: {}}
transitions:
  - {id: t1, from: idle, on: send, to: busy}
```

**Flow** (`flows/send_command.yaml`, id = file stem). One flow is one action a user can see; 5-15 steps is typical.

```yaml
id: send_command
name: Send a command
steps:
  - {link: user_app, text: tap}
  - {link: app_cmd, values: {command: start}}
  - {at: relay, transition: t1}
  - {link: app_cmd, reverse: true, text: result}
```

- A step is exactly one of `link` (a hop, optional `reverse`) or `at` (work inside an object, optional `transition` id from its behavior).
- Continuity: a step must start where the previous one ended (or at its parent/child); otherwise `validate` warns `đứt mạch`.
- `text` is short (about 12 words) and says what happens, not the link name.

## 4. Validate and the edit loop

```
python3 strata.py c4 validate docs/c4                       # 0 errors required; fix gaps (đứt mạch) too
python3 strata.py c4 import docs/c4 --project strata        # upsert; rows missing from the folder are deleted
python3 strata.py c4 flow --project strata --id <flow>      # read the trace back
python3 strata.py c4 export OUT_DIR --project P             # DB -> folder (round trip)
```

- `import` writes nothing if validation reports errors (`--force` skips that check). It also removes task links
  whose object no longer exists, and writes an audit row (`c4-import` with before/after counts).
- Data changes only need a viewer reload. Restart the service only after Python changes.
- Task links: `c4 link|unlink --project P --object X --item ID`, `c4 links --project P --object X`.
  `unlink` also works for an object that was removed from the map.

## 5. Field reference

| Entity | Required | Optional |
|---|---|---|
| object | `id`, `kind`, `name` | `parent`, `summary`, `status`, `tags`, `owns`, `behavior` |
| link | `id`, `from`, `to` | `name`, `summary`, `detail`, `status` |
| contract | `id`, `start`, `end` | `transport`, `body` (any mapping: `signature`, `purpose`, `request`, `response`, `errors`) |
| behavior | `module` (= file stem) | `form`, `initial`, `states`, `transitions` (`id`, `from`, `on`, `to`, `guard`) |
| flow | `steps` | `id` (= file stem), `name` |
| step | exactly one of `link` \| `at` | `reverse` (with `link`), `text`, `values`, `transition` (with `at`) |

Complete example: `tests/fixtures/c4_layered/` (small) and `docs/c4/` (the Strata map).
