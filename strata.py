#!/usr/bin/env python3
"""Strata: project knowledge in SQLite, with a C4 viewer and block pages.

  strata.py init [--db]
  strata.py serve [--db] [--project P] [--port] [--host A,B] [--allow-host NAME]... [--allow-edit|--no-edit] viewer on http://127.0.0.1:PORT
  strata.py page put|validate FILE | list [--project]
  strata.py project add ID --name N [--root --docs-dir --parent --description] | delete ID --yes | list
  strata.py doc validate FILE                     check a doc YAML (no DB)
  strata.py doc scan --project P | set --project P PATH [--feature --status --ord]
  strata.py c4 link|unlink|links --project P --object X --item ID   (links: list only)
  strata.py c4 import DIR --project P [--force] [--dry-run] [--yes] | diff DIR --project P [--json] | export DIR --project P | validate DIR [--json] [--strict]   layered folder (map.yaml + contracts/ behavior/ flows/)
  strata.py c4 context --project P [--object X] [--max-tokens N]
  strata.py c4 coverage --project P [--json]      code files owned by no object, by directory
  strata.py c4 flow --project P [--id F]          numbered step trace (no --id: list flows)
  strata.py c4 contract ID --project P            one contract of a layered project
  strata.py sym index --project P | ls PATH|DIR --project P [--public] | show ID --project P [--sig-only --ctx N] | find PATTERN --project P   Python symbol index (cache next to the DB)
  strata.py search Q [--project P --src item|page|doc --limit N]
  strata.py mcp --role main|coder|reviewer [--db]   MCP server on stdio
  strata.py task context ID [--budget N] [--db]   ticket + rules + c4 + paths in one budgeted text
  strata.py item add --project P --kind task|issue --title T [--label L --body --priority --status --spec FILE|-] | set ID [--status --priority]
  strata.py item list [--project --kind --label --status --owner --ready] | show ID | edit ID [--title --body --spec FILE|- --priority] | ready [--project]
  strata.py item claim ID --as NAME | submit ID --note N [--as NAME] | rework ID --note N | close ID --note N (open -> done) | approve ID [--note --as] | reject ID --note N | release ID | dep add|rm ID DEP   (all: --json)
"""
import argparse, json, pathlib, sqlite3, sys, threading, webbrowser
from strata import blocks, c4_layered, db, service, symbols


def cmd_page(a):
    if a.action == "list":
        for p in db.list_pages(db.connect(a.db), a.project): print(f"{p['project']}/{p['slug']}  [{p['kind']}]  {p['title']}")
        return 0
    try: doc = json.loads(pathlib.Path(a.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e: print("ERROR", e); return 1
    conn = db.init(a.db) if a.action == "put" else (db.connect(a.db) if pathlib.Path(db.db_path(a.db)).exists() else None)
    errs, warns = blocks.validate_doc(doc, conn)
    for w in warns: print("WARN ", w)
    for e in errs: print("ERROR", e)
    if not errs and a.action == "put":
        db.put_page(conn, doc["project"], doc["slug"], doc["title"], doc["kind"], doc["blocks"])
        print(f"ok: {doc['project']}/{doc['slug']}")
    elif not errs: print("ok")
    return 1 if errs else 0


def cmd_doc_validate(a):
    try: errs = blocks.load_doc(pathlib.Path(a.file).read_text(encoding="utf-8"))[1]
    except (OSError, UnicodeDecodeError) as e: errs = [str(e)]
    for e in errs: print("ERROR", e, file=sys.stderr)
    if not errs: print("ok")
    return 1 if errs else 0


def _spec_arg(f):
    if f is None: return None
    try: return json.loads(sys.stdin.read() if f == "-" else pathlib.Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e: raise ValueError(f"--spec: {e}") from None


def _item_line(i): return f"#{i['id']} {i['project']} {i['kind']} [{i['status']}] {i['priority'] or '-'} {i['owner'] or '-'}  {'[' + i['label'] + '] ' if i.get('label') else ''}{i['title']}"


def cmd_item(c, a):
    out = lambda v, text: print(json.dumps(v, ensure_ascii=False) if a.json else text)
    act, who = a.action, getattr(a, "as_", None) or "main"
    if act == "add":
        i = service.add_item(c, "main", a.project, a.kind, a.title, a.body, a.priority, a.status, _spec_arg(a.spec), a.label); out({"id": i}, f"ok: item {i}")
    elif act == "set":
        service.set_item(c, "main", a.id, a.status, a.priority); out({"ok": True}, "ok")
    elif act in ("list", "ready"):
        rows = service.list_items(c, a.project, getattr(a, "kind", None), getattr(a, "status", None), getattr(a, "owner", None), act == "ready" or a.ready, getattr(a, "label", None))
        out(rows, "\n".join(map(_item_line, rows)))
    elif act == "show":
        i = service.get_item(c, a.id)
        out(i, _item_line(i) + "".join(f"\n  depends on #{d['id']} [{d['status']}] {d['title']}" for d in i["depends_on"])
            + "".join(f"\n  blocks #{d['id']} [{d['status']}] {d['title']}" for d in i["blocks"]) + (f"\n{i['body']}" if i["body"] else "")
            + (f"\nspec: {json.dumps(i['spec'], ensure_ascii=False, indent=2)}" if i["spec"] else ""))
    elif act == "edit":
        service.edit_item(c, "main", a.id, a.title, a.body, _spec_arg(a.spec), a.priority); out({"ok": True}, "ok")
    elif act == "dep":
        ch = service.dep(c, "main", a.id, a.dep, a.op == "add"); out({"changed": ch}, "ok" if ch else "no change")
    else:  # status verbs
        cur = c.execute("SELECT status FROM item WHERE id=?", (a.id,)).fetchone()
        if not cur: raise KeyError(f"no item {a.id}")
        if act == "approve" and cur["status"] not in ("proposed", "review"): raise ValueError(f"approve only from proposed or review, item {a.id} is {cur['status']}")
        if act == "rework" and cur["status"] != "review": raise ValueError(f"rework only from review, item {a.id} is {cur['status']}")
        to = {"claim": "doing", "submit": "review", "reject": "rejected", "release": "approved", "rework": "doing", "close": "done"}.get(act) or ("done" if cur["status"] == "review" else "approved")
        service.transition(c, "main", a.id, to, who, getattr(a, "note", None)); out({"ok": True, "status": to}, f"ok: {to}")

    return 0


def cmd_sym(a):
    c = db.init(a.db)
    r = c.execute("SELECT coalesce(p.root, m.root) FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (a.project,)).fetchone()
    if not r or not r[0]: print(f"ERROR project {a.project!r} chưa có root"); return 1
    root, sc = r[0], symbols.connect(symbols.cache_path(db.db_path(a.db)))
    if a.action == "index": print("indexed {}: {} file đổi, {} nguyên, {} xoá".format(a.project, *symbols.index(sc, a.project, root)))
    elif a.action == "ls":
        last = None
        for s in symbols.ls(sc, a.project, a.path, a.public):
            if s["file"] != last and a.path.rstrip("/") != s["file"]: print(f"{s['file']}:")
            last = s["file"]; print(symbols.line(s))
    elif a.action == "find":
        for s in symbols.find(sc, a.project, a.pattern): print(f"{s['id']}  {symbols.line(s).partition(' ')[0]}{s['signature']}")
    else:
        text, ok = symbols.show(sc, a.project, root, a.id, a.sig_only, a.ctx); print(text if ok else "ERROR " + text); return 0 if ok else 1
    return 0


def _idx(a):
    """(symbol cache conn, project) for `c4 validate --project` when the cache file exists, else None (direct ast)."""
    p = symbols.cache_path(db.db_path(a.db))
    return (symbols.connect(p), a.project) if a.project and p.exists() else None


def cmd_write(a):
    """project / doc / item: the only write path besides c4 import and page put."""
    c = db.init(a.db)
    try:
        if a.cmd == "project" and a.action == "add":
            db.add_project(c, a.id, a.name, a.root, a.docs_dir, a.parent, a.description); print("ok:", a.id)
        elif a.cmd == "project" and a.action == "set":
            db.set_project(c, a.id, a.root, a.docs_dir, a.name, a.description); print("ok:", a.id)
        elif a.cmd == "project" and a.action == "delete":
            service.delete_project(c, a.id, a.id if a.yes else None); print("ok: deleted", a.id)
        elif a.cmd == "project":
            for r in c.execute("SELECT id,name,parent,status FROM project ORDER BY id"): print(f"{r['id']}  {r['name']}  parent={r['parent'] or '-'}  [{r['status']}]")
        elif a.cmd == "doc" and a.action == "scan":
            print("scanned {}: {} found, {} missing".format(a.project, *db.scan_docs(c, a.project)))
        elif a.cmd == "search":
            for h in service.search(c, a.q, a.project, a.src, a.limit): print(f"{h['src']}#{h['ref']} {h['project']} {h['title']}")
        elif a.cmd == "task":
            from strata import context
            print(context.build(c, a.id, a.budget))
        elif a.cmd == "c4" and a.action == "context":
            print(c4_layered.context_text(c, a.project, a.object, a.max_tokens))
        elif a.cmd == "c4" and a.action == "coverage":
            r = c.execute("SELECT coalesce(p.root, m.root) FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (a.project,)).fetchone()
            if not r or not r[0]: raise ValueError(f"project {a.project!r} chưa có root")
            owns = {o["id"]: json.loads(o["owns"] or "[]") for o in c.execute("SELECT id, owns FROM c4_object WHERE project=?", (a.project,))}
            cov = c4_layered.coverage(owns, r[0])
            if a.json: print(json.dumps(cov, ensure_ascii=False, indent=1))
            else:
                for d, fs in cov.items(): print(f"{d}/"); [print(f"  {f}") for f in fs]
                print(f"{sum(map(len, cov.values()))} files unowned in {len(cov)} directories")
        elif a.cmd == "c4" and a.action == "flow":
            print(c4_layered.flow_text(c, a.project, a.id))
        elif a.cmd == "c4" and a.action == "contract":
            print(c4_layered.contract_text(c, a.project, a.id))
        elif a.cmd == "c4" and a.action == "import":
            n = c4_layered.import_dir(c, a.dir, a.project, a.force, a.dry_run, a.yes)
            if a.dry_run: print(c4_layered.diff_text(n)); return 0
            print(f"imported {a.project}: " + ", ".join(f"{v} {k}" for k, v in n.items()))
        elif a.cmd == "c4" and a.action == "diff":
            m, errs = c4_layered.load(a.dir)
            if m is None: raise ValueError(c4_layered.fmt(errs[0]))
            df = c4_layered.diff_model(c, m, a.project)
            print(json.dumps(df, ensure_ascii=False, indent=1) if a.json else c4_layered.diff_text(df))
        elif a.cmd == "c4" and a.action == "export":
            c4_layered.export_dir(c, a.project, a.dir); print(f"exported {a.project}: {a.dir}")
        elif a.cmd == "c4" and a.action == "links":
            l = db.links_for(c, a.project, a.object)
            for i in l["items"]: print(f"{i['kind']} #{i['id']} [{i['status']}] {i['title']}")
        elif a.cmd == "c4":
            if not getattr(db, a.action)(c, a.project, a.object, a.item, None): print("no change"); return 0
            print("ok")
        elif a.cmd == "doc":
            db.set_doc(c, a.project, a.path, a.feature, a.status, a.ord); print("ok")
        else:
            cmd_item(c, a)
    except (sqlite3.DatabaseError, ValueError, KeyError, PermissionError) as e:
        print("ERROR", e.args[0] if isinstance(e, KeyError) else e); return 1
    return 0


ITEM_STATUS = ["proposed", "approved", "open", "doing", "review", "done", "rejected"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(name, *args):
        p = sub.add_parser(name); p.add_argument("--db")
        for x in args: p.add_argument(*x[0], **x[1])
        return p
    add("init")
    add("serve", (["--project"], {}), (["--port"], {"type": int, "default": 8740}), (["--host"], {"default": "127.0.0.1"}), (["--allow-host"], {"action": "append", "default": []}), (["--allow-edit"], {"dest": "allow_edit", "action": "store_const", "const": True, "default": None}), (["--no-edit"], {"dest": "allow_edit", "action": "store_const", "const": False, "default": None}))
    pg = sub.add_parser("page"); ps = pg.add_subparsers(dest="action", required=True)
    for n in ("put", "validate"):
        p = ps.add_parser(n); p.add_argument("file"); p.add_argument("--db")
    p = ps.add_parser("list"); p.add_argument("--project"); p.add_argument("--db")
    def group(name, actions):
        g = sub.add_parser(name); gs = g.add_subparsers(dest="action", required=True)
        for n, args in actions.items():
            p = gs.add_parser(n); p.add_argument("--db")
            for x in args: p.add_argument(*x[0], **x[1])
    req = {"required": True}
    group("project", {"add": [(["id"], {}), (["--name"], req), (["--root"], {}), (["--docs-dir"], {}), (["--parent"], {}), (["--description"], {})],
                       "set": [(["id"], {}), (["--name"], {}), (["--root"], {}), (["--docs-dir"], {}), (["--description"], {})],
                       "delete": [(["id"], {}), (["--yes"], {"action": "store_true"})], "list": []})
    group("doc", {"validate": [(["file"], {})], "scan": [(["--project"], req)],
                  "set": [(["--project"], req), (["path"], {}), (["--feature"], {}), (["--status"], {"choices": ["current", "draft", "outdated", "missing"]}), (["--ord"], {"type": int})]})
    idp, asp, notep = (["id"], {"type": int}), (["--as"], {"dest": "as_"}), (["--note"], {})
    js = (["--json"], {"action": "store_true"})
    filt = [(["--project"], {}), (["--kind"], {}), (["--label"], {}), (["--status"], {}), (["--owner"], {})]
    group("item", {"add": [(["--project"], req), (["--kind"], {"required": True, "choices": ["task", "issue"]}), (["--title"], req), (["--label"], {}), (["--body"], {}),
                           (["--priority"], {}), (["--status"], {"choices": ITEM_STATUS, "default": "open"}), (["--spec"], {}), js],
                   "set": [idp, (["--status"], {"choices": ITEM_STATUS}), (["--priority"], {}), js],
                   "list": [*filt, (["--ready"], {"action": "store_true"}), js], "ready": [(["--project"], {}), js], "show": [idp, js],
                   "edit": [idp, (["--title"], {}), (["--body"], {}), (["--spec"], {}), (["--priority"], {}), js],
                   "claim": [idp, (["--as"], {"dest": "as_", "required": True}), js], "submit": [idp, (["--note"], req), asp, js],
                   "approve": [idp, notep, asp, js], "reject": [idp, (["--note"], req), js], "rework": [idp, (["--note"], req), asp, js], "close": [idp, (["--note"], req), js], "release": [idp, js],
                   "dep": [(["op"], {"choices": ["add", "rm"]}), idp, (["dep"], {"type": int}), js]})
    group("task", {"context": [(["id"], {"type": int}), (["--budget"], {"type": int, "default": 12000})]})
    p = sub.add_parser("search"); p.add_argument("q"); p.add_argument("--db"); p.add_argument("--project"); p.add_argument("--limit", type=int, default=30)
    p.add_argument("--src", choices=["item", "page", "doc"])
    group("sym", {"index": [(["--project"], req)], "ls": [(["path"], {}), (["--project"], req), (["--public"], {"action": "store_true"})],
                  "show": [(["id"], {}), (["--project"], req), (["--sig-only"], {"action": "store_true"}), (["--ctx"], {"type": int, "default": 0})],
                  "find": [(["pattern"], {}), (["--project"], req)]})
    add("mcp", (["--role"], {"required": True, "choices": service.ROLES}))
    g4 = sub.add_parser("c4"); gs4 = g4.add_subparsers(dest="action", required=True)
    ref = [(["--project"], req), (["--object"], req), (["--item"], {"type": int})]
    for n, args in {"link": ref, "unlink": ref, "links": ref[:2],
                    "context": [(["--project"], req), (["--object"], {}), (["--max-tokens"], {"type": int, "default": 2000})],
                    "coverage": [(["--project"], req), (["--json"], {"action": "store_true"})],
                    "flow": [(["--project"], req), (["--id"], {})], "contract": [(["id"], {}), (["--project"], req)],
                    "import": [(["dir"], {}), (["--project"], req), (["--force"], {"action": "store_true"}),
                               (["--dry-run"], {"action": "store_true"}), (["--yes"], {"action": "store_true"})],
                    "diff": [(["dir"], {}), (["--project"], req), (["--json"], {"action": "store_true"})],
                    "export": [(["dir"], {}), (["--project"], req)], "validate": [(["dir"], {}), (["--project"], {}), (["--json"], {"action": "store_true"}), (["--strict"], {"action": "store_true"})]}.items():
        p = gs4.add_parser(n); p.add_argument("--db")
        for x in args: p.add_argument(*x[0], **x[1])
    a = ap.parse_args(argv)
    if a.cmd == "doc" and a.action == "validate": return cmd_doc_validate(a)
    if a.cmd == "sym": return cmd_sym(a)
    if a.cmd == "c4" and a.action == "validate": return c4_layered.report(a.dir, _idx(a), json_out=a.json, strict=a.strict)
    if a.cmd in ("project", "doc", "item", "c4", "search", "task"): return cmd_write(a)
    if a.cmd == "mcp":
        from strata import mcp
        return mcp.serve(a.role, a.db)
    if a.cmd == "init":
        db.init(a.db).close(); print("ok:", db.db_path(a.db)); return 0
    if a.cmd == "page": return cmd_page(a)
    from strata import server
    hosts = a.host.split(",")  # vd "127.0.0.1,100.107.55.40": nghe nhiều địa chỉ
    mk = lambda h: server.make_server(a.db, a.project, a.port, h, a.allow_host, hosts, allow_edit=a.allow_edit)
    try:
        srv = mk(hosts[0])
        others = [mk(h) for h in hosts[1:]]
    except ValueError as e: print("ERROR", e); return 1
    for o in others: threading.Thread(target=o.serve_forever, daemon=True).start()
    url = f"http://{hosts[0]}:{srv.server_address[1]}/"
    print(f"Strata: {url}  (db: {db.db_path(a.db)})")
    webbrowser.open(url)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
