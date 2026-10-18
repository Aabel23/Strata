#!/usr/bin/env python3
"""Strata: project knowledge in SQLite, with a C4 viewer and block pages.

  strata.py init [--db]
  strata.py import-yaml FILE --project P [--db]   load a C4 YAML model into the DB
  strata.py validate FILE | --project P [--db]    check structure and code links
  strata.py serve [--db] [--project P] [--port]   viewer on http://127.0.0.1:PORT
  strata.py page put|validate FILE | list [--project]
  strata.py project add ID --name N [--root --docs-dir --parent --description] | list
  strata.py doc scan --project P | set --project P PATH [--feature --status --ord]
  strata.py item add --project P --kind task|issue --title T [--body --priority --status] | set ID [--status --priority]
"""
import argparse, json, pathlib, sqlite3, sys, webbrowser
from strata import blocks, c4, db


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


def cmd_write(a):
    """project / doc / item: the only write path besides import-yaml and page put."""
    c = db.init(a.db)
    try:
        if a.cmd == "project" and a.action == "add":
            db.add_project(c, a.id, a.name, a.root, a.docs_dir, a.parent, a.description); print("ok:", a.id)
        elif a.cmd == "project":
            for r in c.execute("SELECT id,name,parent,status FROM project ORDER BY id"): print(f"{r['id']}  {r['name']}  parent={r['parent'] or '-'}  [{r['status']}]")
        elif a.action == "scan":
            print("scanned {}: {} found, {} missing".format(a.project, *db.scan_docs(c, a.project)))
        elif a.cmd == "doc":
            db.set_doc(c, a.project, a.path, a.feature, a.status, a.ord); print("ok")
        elif a.action == "add":
            print("ok: item", db.add_item(c, a.project, a.kind, a.title, a.body, a.priority, a.status))
        else:
            db.set_item(c, a.id, a.status, a.priority); print("ok")
    except (sqlite3.DatabaseError, ValueError, KeyError) as e:
        print("ERROR", e); return 1
    return 0


ITEM_STATUS = ["proposed", "approved", "open", "doing", "done", "rejected"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(name, *args):
        p = sub.add_parser(name); p.add_argument("--db")
        for x in args: p.add_argument(*x[0], **x[1])
        return p
    add("init")
    add("import-yaml", (["file"], {}), (["--project"], {"required": True}))
    add("validate", (["file"], {"nargs": "?"}), (["--project"], {}))
    add("serve", (["--project"], {}), (["--port"], {"type": int, "default": 8740}))
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
    group("doc", {"scan": [(["--project"], req)],
                  "set": [(["--project"], req), (["path"], {}), (["--feature"], {}), (["--status"], {"choices": ["current", "draft", "outdated", "missing"]}), (["--ord"], {"type": int})]})
    group("item", {"add": [(["--project"], req), (["--kind"], {"required": True, "choices": ["task", "issue"]}), (["--title"], req), (["--body"], {}),
                           (["--priority"], {}), (["--status"], {"choices": ITEM_STATUS, "default": "open"})],
                   "set": [(["id"], {"type": int}), (["--status"], {"choices": ITEM_STATUS}), (["--priority"], {})]})
    a = ap.parse_args(argv)
    if a.cmd in ("project", "doc", "item"): return cmd_write(a)
    if a.cmd == "init":
        db.init(a.db).close(); print("ok:", db.db_path(a.db)); return 0
    if a.cmd == "import-yaml":
        try: n = c4.import_yaml(db.init(a.db), a.file, a.project)
        except (OSError, ValueError, TypeError, AttributeError, sqlite3.IntegrityError) as e: print("ERROR import:", e); return 1
        print(f"imported {a.project}: {n['object']} object, {n['connection']} connection, {n['flow']} flow"); return 0
    if a.cmd == "validate":
        if a.project: return c4.validate_db(db.init(a.db), a.project)
        if a.file: return c4.validate_file(a.file)
        ap.error("validate needs FILE or --project")
    if a.cmd == "page": return cmd_page(a)
    from strata import server
    srv = server.make_server(a.db, a.project, a.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Strata: {url}  (db: {db.db_path(a.db)})")
    webbrowser.open(url)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
