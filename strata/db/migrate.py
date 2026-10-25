import datetime
import os
import pathlib
import re
import shutil
import sqlite3

from .connection import connect, db_path

SCHEMA = pathlib.Path(__file__).resolve().parent / "schema.sql"

def _item_rebuild_due(c):
    return not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone() and bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='item'").fetchone()) \
        and "spec" not in [r[1] for r in c.execute("PRAGMA table_info(item)")]

def _page_rebuild_due(c):
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='page'").fetchone()
    return bool(r) and "'plan'" not in r[0] and not c.execute("SELECT 1 FROM sqlite_master WHERE name='page_old'").fetchone()  # CHECK predates kind 'plan'

def _item_phase_due(c):
    cols = [r[1] for r in c.execute("PRAGMA table_info(item)")]
    return bool(cols) and not {"phase", "label"} <= set(cols)  # ALTER ADD COLUMN: back up first like the rebuilds

def _issue_kind_due(c):
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='item'").fetchone()
    return bool(r) and "'issue'" in r[0]  # CHECK predates label: issues are tasks labelled 'issue' (#203)

def _backup_if_rebuild(path):
    """Copy the DB file to <dir>/backups/strata-YYYYmmdd-HHMMSS.db before a destructive item/page rebuild (one backup for both) (before connect() flips it to WAL, so bytes match)."""
    p = db_path(path)
    if p == ":memory:" or not os.path.exists(p): return
    k = sqlite3.connect(p)
    try: due = _item_rebuild_due(k) or _page_rebuild_due(k) or _item_phase_due(k) or _issue_kind_due(k)
    finally: k.close()
    if due:
        d = pathlib.Path(p).parent / "backups"; d.mkdir(exist_ok=True)
        shutil.copy2(p, d / datetime.datetime.now().strftime("strata-%Y%m%d-%H%M%S.db"))

def _old_c4_due(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name IN ('c4_port','c4_interface')").fetchone())

def _backup_old_c4(path):
    """Before dropping the old single-file C4 format: backups/strata-pre-old-c4-drop-<timestamp>.db via the sqlite backup API."""
    p = db_path(path)
    if p == ":memory:" or not os.path.exists(p): return
    k = sqlite3.connect(p)
    try:
        if not _old_c4_due(k): return
        d = pathlib.Path(p).parent / "backups"; d.mkdir(exist_ok=True)
        dst = sqlite3.connect(d / datetime.datetime.now().strftime("strata-pre-old-c4-drop-%Y%m%d-%H%M%S.db"))
        try: k.backup(dst)
        finally: dst.close()
    finally: k.close()

def _drop_old_c4(c):
    """One-off: C4 rows of projects not imported as a layered folder, orphan c4_link rows, then tables c4_port/c4_interface
    (c4_connection is rebuilt first: its FKs point at c4_port). Layered = c4_meta.source is a folder, not a .yaml file."""
    if not _old_c4_due(c): return
    c.commit(); c.execute("PRAGMA foreign_keys=OFF")
    try:
        keep = "SELECT project FROM c4_meta WHERE source IS NOT NULL AND lower(source) NOT LIKE '%.yaml' AND lower(source) NOT LIKE '%.yml'"
        c.executescript(f"""BEGIN;
            DELETE FROM c4_link WHERE project NOT IN ({keep});
            DELETE FROM c4_connection WHERE project NOT IN ({keep});
            DELETE FROM c4_flow WHERE project NOT IN ({keep});
            DELETE FROM c4_contract WHERE project NOT IN ({keep});
            DELETE FROM c4_behavior WHERE project NOT IN ({keep});
            DELETE FROM c4_object WHERE project NOT IN ({keep});
            DELETE FROM c4_meta WHERE project NOT IN ({keep});
            DELETE FROM c4_link WHERE NOT EXISTS (SELECT 1 FROM c4_object o WHERE o.project=c4_link.project AND o.id=c4_link.object_id);
            CREATE TABLE c4_connection_new(
              id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
              name TEXT, status TEXT, description TEXT, detail TEXT, PRIMARY KEY(project,id));
            INSERT INTO c4_connection_new SELECT id,project,from_id,to_id,name,status,description,detail FROM c4_connection;
            DROP TABLE c4_connection; ALTER TABLE c4_connection_new RENAME TO c4_connection;
            DROP TABLE IF EXISTS c4_port; DROP TABLE IF EXISTS c4_interface;
            COMMIT;""")
    except BaseException:
        c.rollback(); raise
    finally: c.execute("PRAGMA foreign_keys=ON")

def init(path=None):
    _backup_if_rebuild(path)
    _backup_old_c4(path)
    c = connect(path)
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='research'").fetchone() and c.execute("SELECT 1 FROM research").fetchone():
        raise RuntimeError("table research is not empty: move rows to page(kind='research') first")
    rebuild = _migrate(c)
    items, pages = _item_rebuild_due(c), _page_rebuild_due(c)
    if items or pages:  # one transaction: rename + new schema + copy; any error rolls back to the old tables
        c.execute("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, so set it first
        try:
            c.executescript("BEGIN;" + ("DROP TRIGGER IF EXISTS item_ai;DROP TRIGGER IF EXISTS item_au;DROP TRIGGER IF EXISTS item_ad;"
                                        "ALTER TABLE item RENAME TO item_old;" if items else "")
                            + ("DROP TRIGGER IF EXISTS page_ai;DROP TRIGGER IF EXISTS page_au;DROP TRIGGER IF EXISTS page_ad;"
                               "ALTER TABLE page RENAME TO page_old;" if pages else "") + SCHEMA.read_text())
            _finish_item(c); _finish_page(c)
        except BaseException:
            c.rollback(); raise
        finally: c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA.read_text())
    _finish_item(c)
    _finish_page(c)
    _drop_issue_kind(c)
    if rebuild:  # copy rows from the old-CHECK table into the new one
        cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(c4_object_old)"))
        c.execute(f"INSERT INTO c4_object({cols}) SELECT {cols} FROM c4_object_old")
        c.execute("DROP TABLE c4_object_old")
    _drop_old_c4(c)
    c.commit()
    return c

def _finish_item(c):
    """Copy item_old into the rebuilt item table (old `scope` text becomes spec.scope), reindex, integrity-check."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone(): return
    cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(item_old)") if r["name"] != "scope")
    c.execute("DELETE FROM search WHERE src='item'")  # item_ai refills it row by row
    c.execute(f"INSERT INTO item({cols},spec) SELECT {cols}, CASE WHEN scope IS NULL THEN NULL "
              "WHEN json_valid(scope) THEN json_object('scope',json(scope)) ELSE json_object('scope',scope) END FROM item_old")
    c.execute("DROP TABLE item_old")
    if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")
    c.commit()

def _drop_issue_kind(c):
    """Issues become tasks with label 'issue' (open -> approved), then item is rebuilt without 'issue' in its kind CHECK
    (new table, same ids; item_dep keeps pointing at the name `item`). Idempotent."""
    if not _issue_kind_due(c): return
    c.commit()
    c.execute("UPDATE item SET label='issue', kind='task', status=CASE status WHEN 'open' THEN 'approved' ELSE status END WHERE kind='issue'")
    c.commit()
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS item\(.*?\);", SCHEMA.read_text(), re.S).group(0).replace("IF NOT EXISTS item(", "item_new(", 1)
    cols = ",".join(r["name"] for r in c.execute("PRAGMA table_info(item)"))
    c.execute("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, so set it first
    try:
        c.executescript(f"BEGIN;{ddl}INSERT INTO item_new({cols}) SELECT {cols} FROM item;DROP TABLE item;ALTER TABLE item_new RENAME TO item;COMMIT;")
        c.executescript(SCHEMA.read_text())  # index and FTS triggers died with the old table
        if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")
        if c.execute("PRAGMA foreign_key_check").fetchone(): raise RuntimeError("foreign_key_check failed after item rebuild")
    except BaseException:
        c.rollback(); raise
    finally: c.execute("PRAGMA foreign_keys=ON")

def _finish_page(c):
    """Copy page_old (CHECK predates kind 'plan') into the rebuilt page table keeping rowids, so FTS refs stay valid."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='page_old'").fetchone(): return
    cols = ",".join(r[1] for r in c.execute("PRAGMA table_info(page_old)"))
    c.execute("DELETE FROM search WHERE src='page'")  # page_ai refills it row by row
    c.execute(f"INSERT INTO page(rowid,{cols}) SELECT rowid,{cols} FROM page_old")
    c.execute("DROP TABLE page_old"); c.commit()
    if (r := c.execute("PRAGMA integrity_check").fetchone()[0]) != "ok": raise RuntimeError(f"integrity_check: {r}")

# columns added after a table was first created: (table, column, type)
ADDED = [("c4_connection", "description", "TEXT"),
         ("c4_object", "kind", "TEXT"), ("c4_object", "owns", "JSON"), ("c4_object", "behavior", "TEXT"), ("c4_connection", "detail", "TEXT"),
         ("c4_object", "responsibilities", "JSON"), ("c4_object", "state", "TEXT"),
         ("item", "phase", "INT"), ("item", "roadmap", "TEXT"), ("item", "label", "TEXT"), ("doc", "prev_status", "TEXT"), ("doc", "summary", "TEXT"), ("doc", "code", "JSON"), ("c4_meta", "positions", "JSON"), ("c4_meta", "source", "TEXT")]

def _migrate(c):
    """ALTER old tables up to the current schema. Returns True if c4_object was renamed to c4_object_old
    (its type CHECK predates 'file'/'function' and SQLite cannot alter a CHECK) for init to copy back."""
    c.execute("DROP TABLE IF EXISTS object_layout")  # stored layout removed (#185): renderer lays out
    for t, col, typ in ADDED:
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})")]
        if cols and col not in cols: c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='decision'").fetchone():  # decisions removed (#211): drop table, triggers, index rows, links
        c.execute("DELETE FROM search WHERE src='decision'")
        for t in ("decision_ai", "decision_no_replace", "decision_no_delete", "decision_status_only"): c.execute(f"DROP TRIGGER IF EXISTS {t}")
        c.execute("DROP TABLE decision")
    l = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='c4_link'").fetchone()
    if l and "'decision'" in l["sql"]:  # SQLite cannot alter the old CHECK: rebuild with item rows only
        c.execute("CREATE TABLE c4_link_new(project TEXT NOT NULL, object_id TEXT NOT NULL, ref_kind TEXT NOT NULL CHECK(ref_kind IN ('item')), "
                  "ref_id INTEGER NOT NULL, PRIMARY KEY(project,object_id,ref_kind,ref_id))")
        c.execute("INSERT INTO c4_link_new SELECT project,object_id,ref_kind,ref_id FROM c4_link WHERE ref_kind='item'")
        c.execute("DROP TABLE c4_link"); c.execute("ALTER TABLE c4_link_new RENAME TO c4_link")
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='c4_object'").fetchone()
    if r and "'function'" not in r["sql"]:
        c.execute("ALTER TABLE c4_object RENAME TO c4_object_old"); return True
    return False
