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
  (live, future, doing, maintenance, deprecated, removed), `tags`, `owns` (code globs), `behavior` (module file stem),
  `tech` (optional string, C4 notation `[Type: Tech]`, e.g. `tech: Python + SQLite`; kept in the `technology` column, written back by
  `c4 export`, shown as `id [kind: tech] name` in `c4 context` and as a second line on the node in the viewer).
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
python3 strata.py c4 coverage --project P [--json]          # code files owned by no object
```

- `import` writes nothing if validation reports errors (`--force` skips that check). It also removes task links
  whose object no longer exists, and writes an audit row (`c4-import` with before/after counts).
- `validate` returns structured findings: `{id, severity, subject, message, fix}`. `severity` is `error` or `warn`;
  `subject` is the offending file or object; `fix` is a one-line hint. Text output, one line per finding:
  `ERROR [C4-DUP-ID] subject: message (fix: ...)` / `WARN  [C4-FLOW-BREAK] subject: message (fix: ...)`.
- `--json` prints the findings list instead of text. Exit code is non-zero on errors; `--strict` makes warnings fail it too.

| Id | Severity | Fix hint |
|---|---|---|
| `C4-READ` | error | fix the YAML syntax or file permissions |
| `C4-MAP-MISSING` | error | create `map.yaml` in the C4 folder |
| `C4-BAD-SHAPE` | error | use the expected shape (mapping, or a list of `- id: ...`) |
| `C4-UNKNOWN-KEY` | error | remove or rename the key per the schema (`map.yaml`: only `project`, `objects`, `links`) |
| `C4-MISSING-ID` | error | add an `id` to the entry |
| `C4-MISSING-NAME` | error | add a `name` to the object |
| `C4-DUP-ID` | error | rename one of the duplicate ids |
| `C4-BAD-TECH` | error | write tech as text, e.g. 'Python 3.12, sqlite3' |
| `C4-BAD-KIND` | error | use one of the allowed object kinds |
| `C4-BAD-STATUS` | error | use one of the allowed statuses |
| `C4-PARENT-MISSING` | error | point `parent` at an existing object, or add that object |
| `C4-PARENT-CYCLE` | error | break the loop: change the `parent` of one object in the chain |
| `C4-BEHAVIOR-FILE` | error | write a mapping whose `module` matches the file name |
| `C4-BEHAVIOR-MISSING` | error | create `behavior/<module>.yaml` or drop the object's `behavior` field |
| `C4-BEHAVIOR-ORPHAN` | error | add an object with the same id, or delete the behavior file |
| `C4-LINK-END` | error | fix `from`/`to` to point at existing objects |
| `C4-LINK-DETAIL` | error | set `detail` to an existing contract id (`file.id`) or remove it |
| `C4-CONTRACT-BAD` | error | give the contract an id, plus `start` and `end` as `path::Qual.name` |
| `C4-FLOW-ID` | error | make the flow `id` match the file name |
| `C4-FLOW-STEP` | error | write the step as `{link, reverse?}` or `{at, transition?}` with existing ids; `transition` only with `at` |
| `C4-SYMBOL-UNRESOLVED` | warn | fix `path::Qual.name` to match the code, or create the symbol |
| `C4-TRANSITION` | warn | add the transition to the object's behavior, or fix the id |
| `C4-FLOW-BREAK` | warn | add a bridging step or reorder the steps (the `đứt mạch` gap) |
| `C4-PERSON-TARGET` | warn | link the actor to an app or system |
| `C4-COMP-PARENT` | warn | set parent so the chain reaches one app |
| `C4-COMP-CROSS` | warn | link the apps, or move the link to app level |
| `C4-PARENT-LEVEL` | warn | app goes under system; component under app/component/group; actor and store hold nothing |
| `C4-SELF-LINK` | warn | remove the link or point it at another object |
| `C4-LINK-NOLABEL` | warn | add a name that says what flows |
| `C4-LINK-NOPROTO` | warn | set transport in the detail contract or name the protocol in the link name |
| `C4-LINK-DIR` | warn | keep one direction per interaction, or name each as request and reply |
| `C4-LINK-DUP` | warn | merge or rename the duplicate |
| `C4-FILE-OBJECT` | warn | make it a component folder or drop it; files belong in owns |
| `C4-STORE-SHARED` | warn | give the store one owner app and let others call that app |
| `C4-ORPHAN` | warn | link it to the rest or remove it |
| `C4-CYCLE-APP` | warn | break the cycle: invert or drop one dependency |
| `C4-CONTRACT-ORPHAN` | warn | set it as a link's detail or delete it |
| `C4-BEHAVIOR-UNREACHABLE` | warn | add a transition into it or delete the state |
| `C4-VIEW-SIZE` | warn | group children under intermediate objects |
| `C4-OWNS-EMPTY` | warn | fix the path or glob, or remove the entry |
| `C4-OWNS-OVERLAP` | warn | narrow the owns of one object so each file has a single owner |
| `C4-TECH-MISSING` | warn | add tech: the language, framework or engine it runs on (app and store only) |

The semantic rules from `C4-PERSON-TARGET` to `C4-TECH-MISSING` are warnings only; they fail the check only under `--strict`.

- `c4 coverage --project P [--json]` lists code files that no object owns, grouped by directory (hidden directories and
  `venv`, `.venv`, `.git`, `node_modules`, `__pycache__` are skipped; vendored copies elsewhere still count). Text output ends with `N files unowned in M directories`. Use it to find code the map does not cover.
- Data changes only need a viewer reload. Restart the service only after Python changes.
- Task links: `c4 link|unlink --project P --object X --item ID`, `c4 links --project P --object X`.
  `unlink` also works for an object that was removed from the map.

### The Architect editor (viewer toolbar)

The user can also edit the map in the viewer. In the Architect tab the toolbar switches between Select and Edit; in Edit mode it can add, edit and delete an object, and add, edit and delete a link. Deleting an object that has children or links asks for a cascade confirm, and an edit that would drop task links asks for a task-link confirm.

- It edits the same YAML folder you edit (`docs/c4`), not a separate copy. Each edit is checked like `c4 validate` (an edit that introduces a new error is rejected; errors that were already there are not blamed), written to the folder, and imported with an audit row.
- Agents should still prefer editing the files and running `c4 import`. After the user has used the toolbar, re-read the folder before changing it; `git diff docs/c4` shows the user's edits.
- The toolbar cannot edit contracts, flows or behavior, rename an object id, or change a link's from/to. Do those in the files.

### The Code level (derived)

The Architect view has a derived Code level below components. Select a component and click Code, or double-click a component that has no child objects. The panel lists the files the component owns (from its `owns` globs), expands a file lazily into classes and methods, and shows source (capped at 200 lines). It has a filter box, a public-only toggle, kind chips (class, def) and keyboard keys (arrows, Enter, `/` to filter, Escape to close). Deep link: `#<object>/code/<path>::<Qual>`.

- Nothing is stored in the YAML map. The panel is read-only and computed from the files on disk.
- To make a component show code, set `owns` (files or globs) on it. `C4-OWNS-EMPTY` (an `owns` entry matching no file) and `c4 coverage` (code files owned by no object) find the gaps.
- Limits: Python symbols only (other files are listed but have no outline); functions nested inside function bodies are not listed; lists are capped at 500 rows in the panel and 2000 files per component.

## 5. Field reference

| Entity | Required | Optional |
|---|---|---|
| object | `id`, `kind`, `name` | `parent`, `summary`, `status`, `tags`, `owns`, `behavior`, `tech` |
| link | `id`, `from`, `to` | `name`, `summary`, `detail`, `status` |
| contract | `id`, `start`, `end` | `transport`, `body` (any mapping: `signature`, `purpose`, `request`, `response`, `errors`) |
| behavior | `module` (= file stem) | `form`, `initial`, `states`, `transitions` (`id`, `from`, `on`, `to`, `guard`) |
| flow | `steps` | `id` (= file stem), `name` |
| step | exactly one of `link` \| `at` | `reverse` (with `link`), `text`, `values`, `transition` (with `at`) |

Complete example: `tests/fixtures/c4_layered/` (small) and `docs/c4/` (the Strata map).

## 6. Design rules (a map a reader can trace)

Owner-approved layout, distilled from the `strata`, `app_version1.1` and `project1_app` maps. Follow it when you create or remake a map.

**Levels**

1. **Top (context):** actors, the product's big units, and outside systems (`tags: [external]`). A product made of separately
   deployed parts (phone app, server, device) gets one top unit per part, not one wrapper system. A unit that is one process
   is an `app` at the top; a unit that holds several processes or stores is a `system`.
2. **Container:** inside a unit, each running process or data store (`app` / `store`), always with `tech`. A store sits inside
   the unit that owns it.
3. **Component:** what each container is made of, one code folder each, about 4-7 per container. Only leaves `owns` code; a
   parent never owns what its children own (`C4-OWNS-OVERLAP`). Merge a single-file component whose only job is forwarding
   into its caller (`C4-FILE-OBJECT`).

Build the map from the current code (folder READMEs, route tables, entry points), never by porting an older map of another
version.

**Links**

- One link per real call; name what flows, plus the protocol on cross-unit links. Replies are `reverse: true` steps, never
  reverse links.
- **Endpoint links.** Zoomed into a unit, the viewer shows every outside object as its top unit and drops links whose two ends
  are both outside (`lift()` in `viewer/index.html`). So a unit-to-unit hop (for example `app -> server`) vanishes once you zoom
  in. For each cross-unit hop keep the unit-level link that flows use, and add display-only links with an `ep_` prefix:
  - sender side: inner block -> the other side's **top unit** (`a_cloud -> server`);
  - receiver side: the other side's **top unit** -> inner block (`app -> transport`).
  Target the top unit, not the other block: a component-to-component link across apps raises `C4-COMP-CROSS`, and a deeper
  target would show the link twice in the wrong views. Reuse the hop's contract as `detail`.
- An actor may link straight to the component it touches (screen, CLI) as an endpoint link; accept that `C4-PERSON-TARGET`.
- Check the result per view: for the top level and each unit or container with children, list the links that have one end
  outside. Every outside unit the code talks to must appear there.

**Flows**

- One user-visible action per flow. Prefix the name with its reading order: `"3. Log in"`.
- Plumbing shared by every request (envelope, auth) appears once, in flow `0`; business flows skip it.
- One hop per step; show app-internal hops only when they add information.
- Add a reverse step only when continuity needs it. A call into a store that sits inside the same unit needs no return step
  before that unit replies.
- Aim for at most about 20 steps and zero `C4-FLOW-BREAK`. Step text says what happens and names the key route or symbol, in
  about 12 words.

**Warnings**

0 errors and 0 flow breaks are required. A remaining warning must be a real code fact (two components calling each other, a
store shared by two processes) or a tool limit (non-Python contract symbols). Report it to the user; do not bend the map to
hide it.

Reference map for this layout: `project1_app` (`/home/abel/project/internproj/project1_app/documentation/c4`).
