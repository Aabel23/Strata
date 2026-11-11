"""File explorer backing (viewer tab Files): list, read and change files under one registered project root.
No DB and no audit: these are the user's own working files, like the terminal. Every path is relative to the root,
may not name `.git`, and may not resolve (through symlinks) to anywhere outside the root."""
import os, pathlib, shutil, tempfile

MAX_FILE = 2 * 1024 * 1024   # largest file the editor opens or saves
MAX_LIST = 5000              # entries returned for one folder
HIDDEN = {".git"}


class FileError(ValueError): pass
class Conflict(FileError): pass


def resolve(root, rel):
    """Absolute path of `rel` under `root`. Rejects NUL, '.', '..', `.git`, and anything that resolves outside the root."""
    if not isinstance(rel, str) or "\0" in rel or len(rel) > 4096: raise FileError("bad path")
    segs = [s for s in rel.split("/") if s]
    if any(s in (".", "..") or s in HIDDEN for s in segs): raise FileError("bad path")
    base = pathlib.Path(root).resolve()
    p = base.joinpath(*segs)
    try: real = p.resolve()
    except (OSError, RuntimeError): raise FileError("bad path")
    if not real.is_relative_to(base) or HIDDEN & set(real.relative_to(base).parts): raise FileError("path leaves the project")
    return p


def _rel(root, p): return p.relative_to(pathlib.Path(root).resolve()).as_posix()
def _mtime(p): return str(p.stat().st_mtime_ns)  # a string: nanoseconds do not fit a JS number


def listing(root, rel=""):
    """One folder, folders first. Lazy: the viewer asks for a folder when it is expanded."""
    d = resolve(root, rel)
    if not d.is_dir(): raise FileNotFoundError(rel)
    out = []
    with os.scandir(d) as it:
        for e in it:
            if e.name in HIDDEN: continue
            try: is_dir = e.is_dir()
            except OSError: is_dir = False
            out.append({"name": e.name, "dir": is_dir})
    out.sort(key=lambda x: (not x["dir"], x["name"].lower(), x["name"]))
    return {"path": _rel(root, d) if rel.strip("/") else "", "entries": out[:MAX_LIST], "more": max(0, len(out) - MAX_LIST)}


def read(root, rel):
    f = resolve(root, rel)
    if not f.is_file(): raise FileNotFoundError(rel)
    size = f.stat().st_size
    base = {"path": _rel(root, f), "size": size, "mtime": _mtime(f)}
    if size > MAX_FILE: return {**base, "skipped": f"File is too large to edit here ({size // 1024} KB, limit {MAX_FILE // 1024} KB)."}
    data = f.read_bytes()
    try:
        if b"\0" in data: raise ValueError
        text = data.decode("utf-8")
    except ValueError: return {**base, "skipped": "Binary file or not UTF-8 text: not shown."}
    return {**base, "text": text}


def write(root, rel, text, mtime=None):
    """Save an existing file. `mtime` is the stamp the editor loaded: a different one on disk means someone else changed the file."""
    f = resolve(root, rel)
    if not f.is_file(): raise FileNotFoundError(rel)
    data = text.encode("utf-8")
    if len(data) > MAX_FILE: raise FileError("file too large")
    if mtime is not None and mtime != _mtime(f): raise Conflict("The file changed on disk since it was opened.")
    real = f.resolve()  # write through a symlink instead of replacing it
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=".strata-save-")
    try:
        with os.fdopen(fd, "wb") as h: h.write(data)
        os.chmod(tmp, real.stat().st_mode & 0o7777)
        os.replace(tmp, real)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return {"path": _rel(root, f), "size": len(data), "mtime": _mtime(f)}


def _new(root, rel):
    p = resolve(root, rel)
    if p == pathlib.Path(root).resolve(): raise FileError("bad path")
    if p.exists() or p.is_symlink(): raise Conflict("A file or folder with that name already exists.")
    if not p.parent.is_dir(): raise FileNotFoundError(rel)
    return p


def create(root, rel, folder=False):
    p = _new(root, rel)
    if folder: p.mkdir()
    else: p.open("x").close()
    return {"path": _rel(root, p), "dir": folder}


def rename(root, rel, to):
    src, dst = resolve(root, rel), _new(root, to)
    if src == pathlib.Path(root).resolve(): raise FileError("bad path")
    if not (src.exists() or src.is_symlink()): raise FileNotFoundError(rel)
    os.rename(src, dst)
    return {"path": _rel(root, dst), "dir": dst.is_dir()}


def delete(root, rel, recursive=False):
    """Files and empty folders; a folder with content only when `recursive` (the viewer asks first)."""
    p = resolve(root, rel)
    if p == pathlib.Path(root).resolve(): raise FileError("bad path")
    if p.is_symlink() or p.is_file(): p.unlink()
    elif p.is_dir():
        if recursive: shutil.rmtree(p)
        else:
            try: p.rmdir()
            except OSError: raise Conflict("The folder is not empty.")
    else: raise FileNotFoundError(rel)
    return {"path": rel.strip("/")}
