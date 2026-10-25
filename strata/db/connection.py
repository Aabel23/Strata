import os
import pathlib
import sqlite3

DatabaseError = sqlite3.DatabaseError
Row = sqlite3.Row

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_NEW_DB = _ROOT / "database" / "strata.db"
_OLD_DB = _ROOT / "strata.db"

DEFAULT_DB = str(_NEW_DB if _NEW_DB.exists() else (_OLD_DB if _OLD_DB.exists() else _NEW_DB))

def db_path(path=None):
    if path:
        return str(path)
    env = os.environ.get("STRATA_DB")
    if env:
        return env
    if _NEW_DB.exists():
        return str(_NEW_DB)
    if _OLD_DB.exists():
        return str(_OLD_DB)
    return DEFAULT_DB

def connect(path=None, **kwargs):
    p = db_path(path)
    if p != ":memory:":
        parent = pathlib.Path(p).parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("timeout", 30)
    c = sqlite3.connect(p, **kwargs)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")  # concurrent writers (MCP/CLI/server) wait instead of 'database is locked'
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c
