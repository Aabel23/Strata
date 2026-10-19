#!/usr/bin/env python3
"""Strata: project knowledge in SQLite, with a C4 viewer and block pages.

  strata.py init [--db]
  strata.py import-yaml FILE --project P [--force] [--db]   load a C4 YAML model into the DB
  strata.py validate FILE | --project P [--db]    check structure and code links
  strata.py serve [--db] [--project P] [--port] [--host A,B] [--allow-host NAME]... viewer on http://127.0.0.1:PORT
  strata.py page put|validate FILE | list [--project]
  strata.py project add ID --name N [--root --docs-dir --parent --description] | list
  strata.py doc validate FILE                     check a doc YAML (no DB)
  strata.py doc scan --project P | set --project P PATH [--feature --status --ord]
  strata.py c4 link|unlink|links --project P --object X [--item ID | --decision ID]   (links: list only)
  strata.py c4 context --project P [--object X] [--max-tokens N]
  strata.py c4 flow --project P [--id F]          numbered step trace (no --id: list flows)
  strata.py search Q [--project P --src item|decision|page|doc --limit N]
  strata.py decision add --project P --title T --context C --decision D --consequences Q --rejected R [--supersedes N] | set N --status S
  strata.py mcp --role main|coder|reviewer [--db]   MCP server on stdio
  strata.py item add --project P --kind task|issue|step|gate --title T [--body --priority --status --spec FILE|-] | set ID [--status --priority]
  strata.py item list [--project --kind --status --owner --ready] | show ID | edit ID [--title --body --spec FILE|- --priority] | ready [--project]
  strata.py item claim ID --as NAME | submit ID --note N [--as NAME] | approve ID [--note --as] | reject ID --note N | release ID | dep add|rm ID DEP   (all: --json)
"""
import argparse, json, pathlib, sqlite3, sys, threading, webbrowser
from strata import blocks, c4, db, service


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


def _item_line(i): return f"#{i['id']} {i['project']} {i['kind']} [{i['status']}] {i['priority'] or '-'} {i['owner'] or '-'}  {i['title']}"


def cmd_item(c, a):
    out = lambda v, text: print(json.dumps(v, ensure_ascii=False) if a.json else text)
    act, who = a.action, getattr(a, "as_", None) or "main"
    if act == "add":
        i = service.add_item(c, "main", a.project, a.kind, a.title, a.body, a.priority, a.status, _spec_arg(a.spec)); out({"id": i}, f"ok: item {i}")
    elif act == "set":
        service.set_item(c, "main", a.id, a.status, a.priority); out({"ok": True}, "ok")
    elif act in ("list", "ready"):
        rows = service.list_items(c, a.project, getattr(a, "kind", None), getattr(a, "status", None), getattr(a, "owner", None), act == "ready" or a.ready)
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
        to = {"claim": "doing", "submit": "review", "reject": "rejected", "release": "approved"}.get(act) or ("done" if cur["status"] == "review" else "approved")
        service.transition(c, "main", a.id, to, who, getattr(a, "note", None)); out({"ok": True, "status": to}, f"ok: {to}")


def cmd_write(a):
    """project / doc / item: the only write path besides import-yaml and page put."""
    c = db.init(a.db)
    try:
        if a.cmd == "project" and a.action == "add":
            db.add_project(c, a.id, a.name, a.root, a.docs_dir, a.parent, a.description); print("ok:", a.id)
        elif a.cmd == "project":
            for r in c.execute("SELECT id,name,parent,status FROM project ORDER BY id"): print(f"{r['id']}  {r['name']}  parent={r['parent'] or '-'}  [{r['status']}]")
        elif a.cmd == "doc" and a.action == "scan":
            print("scanned {}: {} found, {} missing".format(a.project, *db.scan_docs(c, a.project)))
        elif a.cmd == "decision" and a.action == "add":
            print("ok: decision", service.add_decision(c, "main", a.project, a.title, a.context, a.decision, a.consequences, a.rejected, a.supersedes))
        elif a.cmd == "decision":
            service.set_decision_status(c, "main", a.id, a.status); print("ok")
        elif a.cmd == "search":
            for h in service.search(c, a.q, a.project, a.src, a.limit): print(f"{h['src']}#{h['ref']} {h['project']} {h['title']}")
        elif a.cmd == "c4" and a.action == "context":
            print(c4.context_text(c, a.project, a.object, a.max_tokens))
        elif a.cmd == "c4" and a.action == "flow":
            print(c4.flow_text(c, a.project, a.id))
        elif a.cmd == "c4" and a.action == "links":
            l = db.links_for(c, a.project, a.object)
            for i in l["items"]: print(f"{i['kind']} #{i['id']} [{i['status']}] {i['title']}")
            for d in l["decisions"]: print(f"decision #{d['id']} [{d['status']}] {d['title']}")
        elif a.cmd == "c4":
            if not getattr(db, a.action)(c, a.project, a.object, a.item, a.decision): print("no change"); return 0
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
    add("import-yaml", (["file"], {}), (["--project"], {"required": True}), (["--force"], {"action": "store_true"}))
    add("validate", (["file"], {"nargs": "?"}), (["--project"], {}))
    add("serve", (["--project"], {}), (["--port"], {"type": int, "default": 8740}), (["--host"], {"default": "127.0.0.1"}), (["--allow-host"], {"action": "append", "default": []}))
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
    group("project", {"add": [(["id"], {}), (["--name"], req), (["--root"], {}), (["--docs-dir"], {}), (["--parent"], {}), (["--description"], {})], "list": []})
    group("doc", {"validate": [(["file"], {})], "scan": [(["--project"], req)],
                  "set": [(["--project"], req), (["path"], {}), (["--feature"], {}), (["--status"], {"choices": ["current", "draft", "outdated", "missing"]}), (["--ord"], {"type": int})]})
    idp, asp, notep = (["id"], {"type": int}), (["--as"], {"dest": "as_"}), (["--note"], {})
    js = (["--json"], {"action": "store_true"})
    filt = [(["--project"], {}), (["--kind"], {}), (["--status"], {}), (["--owner"], {})]
    group("item", {"add": [(["--project"], req), (["--kind"], {"required": True, "choices": ["task", "issue", "step", "gate"]}), (["--title"], req), (["--body"], {}),
                           (["--priority"], {}), (["--status"], {"choices": ITEM_STATUS, "default": "open"}), (["--spec"], {}), js],
                   "set": [idp, (["--status"], {"choices": ITEM_STATUS}), (["--priority"], {}), js],
                   "list": [*filt, (["--ready"], {"action": "store_true"}), js], "ready": [(["--project"], {}), js], "show": [idp, js],
                   "edit": [idp, (["--title"], {}), (["--body"], {}), (["--spec"], {}), (["--priority"], {}), js],
                   "claim": [idp, (["--as"], {"dest": "as_", "required": True}), js], "submit": [idp, (["--note"], req), asp, js],
                   "approve": [idp, notep, asp, js], "reject": [idp, (["--note"], req), js], "release": [idp, js],
                   "dep": [(["op"], {"choices": ["add", "rm"]}), idp, (["dep"], {"type": int}), js]})
    p = sub.add_parser("search"); p.add_argument("q"); p.add_argument("--db"); p.add_argument("--project"); p.add_argument("--limit", type=int, default=30)
    p.add_argument("--src", choices=["item", "decision", "page", "doc"])
    group("decision", {"add": [(["--project"], req), (["--title"], req), (["--context"], req), (["--decision"], req), (["--consequences"], req),
                               (["--rejected"], req), (["--supersedes"], {"type": int})],
                       "set": [(["id"], {"type": int}), (["--status"], {"required": True, "choices": ["proposed", "accepted", "superseded"]})]})
    add("mcp", (["--role"], {"required": True, "choices": service.ROLES}))
    ref = [(["--project"], req), (["--object"], req), (["--item"], {"type": int}), (["--decision"], {"type": int})]
    group("c4", {"link": ref, "unlink": ref, "links": ref[:2],
                 "context": [(["--project"], req), (["--object"], {}), (["--max-tokens"], {"type": int, "default": 2000})],
                 "flow": [(["--project"], req), (["--id"], {})]})
    a = ap.parse_args(argv)
    if a.cmd == "doc" and a.action == "validate": return cmd_doc_validate(a)
    if a.cmd in ("project", "doc", "item", "c4", "search", "decision"): return cmd_write(a)
    if a.cmd == "mcp":
        from strata import mcp
        return mcp.serve(a.role, a.db)
    if a.cmd == "init":
        db.init(a.db).close(); print("ok:", db.db_path(a.db)); return 0
    if a.cmd == "import-yaml":
        try: n = c4.import_yaml(db.init(a.db), a.file, a.project, a.force)
        except (OSError, ValueError, TypeError, AttributeError, sqlite3.IntegrityError) as e: print("ERROR import:", e); return 1
        print(f"imported {a.project}: {n['object']} object, {n['connection']} connection, {n['flow']} flow"); return 0
    if a.cmd == "validate":
        if a.project: return c4.validate_db(db.init(a.db), a.project)
        if a.file: return c4.validate_file(a.file)
        ap.error("validate needs FILE or --project")
    if a.cmd == "page": return cmd_page(a)
    from strata import server
    hosts = a.host.split(",")  # vd "127.0.0.1,100.107.55.40": nghe nhiều địa chỉ
    mk = lambda h: server.make_server(a.db, a.project, a.port, h, a.allow_host, hosts)
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
