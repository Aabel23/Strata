"""Symbol index of Python source (stdlib ast) in a rebuildable cache DB next to strata.db (design: docs/research/c4-layered-map-format.yaml)."""
import ast, hashlib, os, pathlib, posixpath, sqlite3

SKIP = {"venv", ".venv", ".git", "node_modules", "__pycache__"}
CAP = 200
SCHEMA = """CREATE TABLE IF NOT EXISTS file(project TEXT, path TEXT, sha256 TEXT, mtime REAL, size INT, PRIMARY KEY(project, path));
CREATE TABLE IF NOT EXISTS symbol(project TEXT, id TEXT, file TEXT, kind TEXT, name TEXT, parent_id TEXT, signature TEXT, start_line INT, end_line INT,
  doc1 TEXT, visibility TEXT, body_hash TEXT, PRIMARY KEY(project, id));
CREATE INDEX IF NOT EXISTS symbol_file ON symbol(project, file);"""


def cache_path(db_path):
    """Cache DB sits next to the main DB: strata.db -> strata.symbols.db."""
    p = pathlib.Path(db_path); return p.with_name(p.stem + ".symbols.db")


def connect(path):
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row; c.executescript(SCHEMA); return c


def inside(root, rel):
    """Resolved Path of `rel` under `root`, or None when absolute or escaping root (.. or symlink)."""
    if os.path.isabs(rel) or pathlib.PureWindowsPath(rel).is_absolute(): return None
    f = (pathlib.Path(root) / rel).resolve()
    return f if f.is_relative_to(pathlib.Path(root).resolve()) else None


def norm(rel):
    """Canonical cache key for a rel path (a/../a/x.py -> a/x.py); None when absolute, escaping root or empty."""
    if os.path.isabs(rel) or pathlib.PureWindowsPath(rel).is_absolute(): return None
    n = posixpath.normpath(rel.replace("\\", "/"))
    return None if n in (".", "..") or n.startswith("../") else n


def _like(t): return t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sig(n):
    if isinstance(n, ast.ClassDef): return f"({', '.join(ast.unparse(b) for b in n.bases)})" if n.bases else ""
    return f"({ast.unparse(n.args)})" + (f" -> {ast.unparse(n.returns)}" if n.returns else "")


def _walk(body, rel, lines, parent=None):
    for n in body:
        if not isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)): continue
        qual = f"{parent.partition('::')[2]}.{n.name}" if parent else n.name
        sid = f"{rel}::{qual}"
        start = min([n.lineno, *(d.lineno for d in n.decorator_list)])
        doc = (ast.get_docstring(n) or "").strip().split("\n")[0]
        yield (sid, rel, "class" if isinstance(n, ast.ClassDef) else "async def" if isinstance(n, ast.AsyncFunctionDef) else "def", n.name, parent,
               _sig(n), start, n.end_lineno, doc, "private" if n.name.startswith("_") else "public",
               hashlib.sha256("\n".join(lines[start - 1:n.end_lineno]).encode()).hexdigest()[:16])
        if isinstance(n, ast.ClassDef): yield from _walk(n.body, rel, lines, sid)


def _index_file(c, project, rel, f):
    """Re-parse one file if its mtime/size changed and then its sha256 differs. True when re-parsed."""
    st = f.stat(); row = c.execute("SELECT * FROM file WHERE project=? AND path=?", (project, rel)).fetchone()
    if row and row["mtime"] == st.st_mtime and row["size"] == st.st_size: return False
    data = f.read_bytes(); sha = hashlib.sha256(data).hexdigest()
    if row and row["sha256"] == sha:
        c.execute("UPDATE file SET mtime=?, size=? WHERE project=? AND path=?", (st.st_mtime, st.st_size, project, rel)); return False
    try: rows = list(_walk(ast.parse(data.decode("utf-8")).body, rel, data.decode("utf-8").split("\n")))
    except (SyntaxError, ValueError): rows = []
    c.execute("DELETE FROM symbol WHERE project=? AND file=?", (project, rel))
    c.executemany("INSERT OR IGNORE INTO symbol VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [(project, *r) for r in rows])  # first of two same-id defs wins
    c.execute("INSERT OR REPLACE INTO file VALUES(?,?,?,?,?)", (project, rel, sha, st.st_mtime, st.st_size))
    return True


def index(c, project, root):
    """Index every .py under root; returns (reparsed, unchanged, removed)."""
    root = pathlib.Path(root).resolve(); seen, n = set(), 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        for fn in fns:
            if not fn.endswith(".py"): continue
            rel = (pathlib.Path(dp) / fn).relative_to(root).as_posix()
            f = inside(root, rel)
            if f is None or not f.is_file(): continue  # symlink out of root
            seen.add(rel); n += _index_file(c, project, rel, f)
    gone = [r[0] for r in c.execute("SELECT path FROM file WHERE project=?", (project,)) if r[0] not in seen]
    for rel in gone:
        c.execute("DELETE FROM symbol WHERE project=? AND file=?", (project, rel)); c.execute("DELETE FROM file WHERE project=? AND path=?", (project, rel))
    c.commit(); return n, len(seen) - n, len(gone)


def refresh(c, project, root, rel):
    """Bring one file up to date with disk (hash re-check before slicing). False when the path is outside root / not a file."""
    rel = norm(rel); f = rel and inside(root, rel)
    if not f or not f.is_file() or f.suffix != ".py": return False
    _index_file(c, project, rel, f); c.commit(); return True


def line(r): return f"{r['kind']} {r['id'].partition('::')[2]}{r['signature']}" + (f" -- {r['doc1']}" if r["doc1"] else "")


def ls(c, project, target, public=False):
    t = target.rstrip("/")
    rows = c.execute("SELECT * FROM symbol WHERE project=? AND (file=? OR file LIKE ? ESCAPE '\\') ORDER BY file, start_line", (project, t, _like(t) + "/%" if t else "%")).fetchall()
    return [r for r in rows if not public or r["visibility"] == "public"]


def find(c, project, pat):
    return c.execute("SELECT * FROM symbol WHERE project=? AND id LIKE ? ESCAPE '\\' ORDER BY id", (project, f"%{_like(pat)}%")).fetchall()


def show(c, project, root, sid, sig_only=False, ctx=0):
    """(text, ok). Prints the symbol's lines from disk; a dead id lists candidates."""
    path, _, qual = sid.partition("::")
    if not qual: return "sai dạng path::Qual.name", False
    path = norm(path) if inside(root, path) else None
    if path is None: return f"{sid.partition('::')[0]}: ngoài root, từ chối đọc", False
    f = inside(root, path); sid = f"{path}::{qual}"
    if not refresh(c, project, root, path): return f"không có file Python {path}", False
    r = c.execute("SELECT * FROM symbol WHERE project=? AND id=?", (project, sid)).fetchone()
    if not r:
        cand = c.execute("SELECT id FROM symbol WHERE project=? AND name=?", (project, qual.rsplit(".", 1)[-1])).fetchall()
        return f"không có {sid}" + "".join(f"\n  ứng viên: {x[0]}" for x in cand), False
    head = f"# {r['id']} dòng {r['start_line']}-{r['end_line']}"
    if sig_only: return f"{head}\n{line(r)}", True
    try: src = f.read_text(encoding="utf-8").split("\n")
    except (UnicodeDecodeError, OSError): return f"{path}: không đọc được (không phải UTF-8)", False
    a, b = max(1, r["start_line"] - ctx), min(len(src), r["end_line"] + ctx)
    cut = b - a + 1 > CAP
    if cut: b = a + CAP - 1
    return "\n".join([head, *src[a - 1:b]]) + (f"\n... cắt ở {CAP} dòng" if cut else ""), True


def resolves(c, project, root, sym):
    """True/False from the index when `path::qual` is fresh in it, None when the index cannot say (file missing/stale/unindexed)."""
    path, _, qual = sym.partition("::"); path = norm(path); sym = f"{path}::{qual}"
    f = path and inside(root, path)
    if not f or not f.is_file(): return None
    st = f.stat(); row = c.execute("SELECT mtime, size FROM file WHERE project=? AND path=?", (project, path)).fetchone()
    if not row or (row["mtime"], row["size"]) != (st.st_mtime, st.st_size): return None
    return c.execute("SELECT 1 FROM symbol WHERE project=? AND id=?", (project, sym)).fetchone() is not None
