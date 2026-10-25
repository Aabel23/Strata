"""Deterministic comparison between layered C4 links and tracked source imports."""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess

from strata import c4_layered, symbols

CODE_EXT = c4_layered.CODE_EXT
DRIFT_EXT = {".py", ".js", ".html"}
_HTML_SRC = re.compile(r"<script\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _tracked(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        raise ValueError(f"cannot list tracked files under {root}; project root must be in a Git worktree")
    files = set()
    for raw in out.stdout.split(b"\0"):
        if not raw:
            continue
        p = pathlib.PurePosixPath(os.fsdecode(raw))
        if p.suffix.lower() not in CODE_EXT or any(x in symbols.SKIP or x.startswith(".") for x in p.parts):
            continue
        if any(x.lower() in {"test", "tests", "vendor", "vendors", "coverage"} for x in p.parts):
            continue
        if p.name.endswith(".min.js"):
            continue
        files.add(p.as_posix())
    return files


def _resolve(root, importer, target):
    """Resolve a literal local import to a tracked path; bare package imports are external."""
    importer_parts = pathlib.PurePosixPath(importer).parts
    if target.startswith("/"):
        # Strata serves /app.js from viewer/app.js; other projects resolve URL
        # root paths from the repository root.
        mount = ("viewer",) if importer_parts and importer_parts[0] == "viewer" else ()
        p = pathlib.PurePosixPath(*mount, target.lstrip("/")).as_posix()
    elif target.startswith("."):
        p = (pathlib.PurePosixPath(importer).parent / target).as_posix()
    else:
        return None
    p = pathlib.PurePosixPath(os.path.normpath(p))
    if p.is_absolute() or ".." in p.parts:
        return None
    base = root.joinpath(*p.parts)
    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(ext) for ext in (".py", ".js", ".html"))
        candidates.extend(base / ("index" + ext) for ext in (".py", ".js", ".html"))
        candidates.append(base / "__init__.py")
    return next((x.relative_to(root).as_posix() for x in candidates if x.is_file()), None)


def _python_edges(root, tracked):
    edges = set()
    by_module = {}
    for rel in tracked:
        p = pathlib.PurePosixPath(rel)
        if p.suffix == ".py":
            mod = list(p.with_suffix("").parts)
            if mod[-1] == "__init__": mod.pop()
            by_module[".".join(mod)] = rel
    for rel in sorted(tracked):
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(root.joinpath(*pathlib.PurePosixPath(rel).parts).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods.extend((a.name, None) for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                package = list(pathlib.PurePosixPath(rel).parent.parts)
                if n.level:
                    package = package[:max(0, len(package) - n.level + 1)]
                    base = ".".join([*package, n.module] if n.module else package)
                else:
                    base = n.module or ""
                mods.append((base, n.names))
            for mod, names in mods:
                # Importing a package always loads its initializer; imported
                # submodules are separate edges when their module files exist.
                parts = mod.split(".") if mod else []
                dests = {by_module[".".join(parts[:i])] for i in range(1, len(parts) + 1)
                         if ".".join(parts[:i]) in by_module}
                if names:
                    for alias in names:
                        submodule = ".".join(filter(None, (mod, alias.name)))
                        subparts = submodule.split(".")
                        dests.update(by_module[".".join(subparts[:i])] for i in range(1, len(subparts) + 1)
                                     if ".".join(subparts[:i]) in by_module)
                edges.update((rel, dest) for dest in dests if dest != rel)
    return edges


def _js_specifiers(text):
    """Yield literal import targets while ignoring comments and unrelated strings."""
    tokens, i, n = [], 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i + 2); i = n if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2); i = n if end < 0 else end + 2
        elif text[i] in "'\"`":
            quote, start = text[i], i + 1
            i += 1
            while i < n:
                if text[i] == "\\": i += 2
                elif text[i] == quote: break
                else: i += 1
            tokens.append(("string", text[start:min(i, n)]))
            i = min(i + 1, n)
        elif text[i].isalpha() or text[i] in "_$":
            start = i; i += 1
            while i < n and (text[i].isalnum() or text[i] in "_$"): i += 1
            tokens.append(("id", text[start:i]))
        else:
            tokens.append(("punct", text[i])); i += 1

    targets, i = [], 0
    while i < len(tokens):
        typ, val = tokens[i]
        if typ == "id" and val == "require" and i + 2 < len(tokens) and tokens[i + 1] == ("punct", "(") and tokens[i + 2][0] == "string":
            targets.append(tokens[i + 2][1]); i += 3; continue
        if typ == "id" and val in ("import", "export"):
            j = i + 1
            if val == "import" and j < len(tokens) and tokens[j][0] == "string":
                targets.append(tokens[j][1]); i = j + 1; continue
            if val == "import" and j < len(tokens) and tokens[j] == ("punct", "("):
                j += 1
                if j < len(tokens) and tokens[j][0] == "string": targets.append(tokens[j][1])
                i = j + 1; continue
            while j < len(tokens) and tokens[j] not in (("punct", ";"), ("id", "import"), ("id", "export")):
                if tokens[j] == ("id", "from") and j + 1 < len(tokens) and tokens[j + 1][0] == "string":
                    targets.append(tokens[j + 1][1]); break
                j += 1
            i = j + 1; continue
        i += 1
    return targets


def _js_edges(root, tracked):
    edges = set()
    for rel in sorted(tracked):
        if pathlib.PurePosixPath(rel).suffix.lower() not in (".js", ".html"):
            continue
        try:
            text = root.joinpath(*pathlib.PurePosixPath(rel).parts).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        targets = _HTML_SRC.findall(re.sub(r"<!--.*?-->", "", text, flags=re.S)) if rel.lower().endswith(".html") else _js_specifiers(text)
        for target in targets:
            if target.startswith(("http:", "https:", "//", "data:")):
                continue
            dest = _resolve(root, rel, target)
            if dest in tracked and dest != rel:
                edges.add((rel, dest))
    return edges


def _model(c, project):
    objects = {r["id"]: dict(r) for r in c.execute("SELECT id,type AS kind,parent,status,owns FROM c4_object WHERE project=?", (project,))}
    for o in objects.values():
        o["owns"] = json.loads(o["owns"] or "[]")
    links = [dict(r) for r in c.execute("SELECT id,from_id AS `from`,to_id AS `to`,status FROM c4_connection WHERE project=?", (project,))]
    return objects, links


def analyze(c, project):
    row = c.execute("SELECT coalesce(p.root,m.root) root FROM project p LEFT JOIN c4_meta m ON m.project=p.id WHERE p.id=?", (project,)).fetchone()
    if not row or not row["root"]:
        raise ValueError(f"project {project!r} has no root")
    root = pathlib.Path(row["root"]).resolve()
    if not root.is_dir():
        raise ValueError(f"project root does not exist: {root}")
    objects, links = _model(c, project)
    owned = {oid: o["owns"] for oid, o in objects.items() if o["owns"]}
    active = {oid: owns for oid, owns in owned.items() if objects[oid].get("status", "live") != "future"}
    expanded = c4_layered._expand(owned, root)
    active_expanded = c4_layered._expand(active, root)
    tracked = _tracked(root)
    tracked_sources = {f for f in tracked if pathlib.PurePosixPath(f).suffix in DRIFT_EXT}
    tracked_code = {f for f in tracked_sources if pathlib.PurePosixPath(f).name != "__init__.py"}
    owner_apps = {}
    for oid in active_expanded:
        cur, seen = oid, set()
        while cur in objects and cur not in seen:
            seen.add(cur)
            if objects[cur]["kind"] == "app":
                break
            cur = objects[cur].get("parent")
        app = cur if cur in objects and objects[cur]["kind"] == "app" else oid
        for ent in active_expanded.get(oid, {}).values():
            for f in ent:
                if f in tracked_sources:
                    owner_apps.setdefault(f, set()).add(app)
    owned_files = {f for ents in active_expanded.values() for fs in ents.values() for f in fs}

    code_edges = _python_edges(root, tracked) | _js_edges(root, tracked)
    app_edges = set()
    for src, dst in code_edges:
        a, b = owner_apps.get(src, set()), owner_apps.get(dst, set())
        if len(a) == len(b) == 1 and next(iter(a)) != next(iter(b)):
            app_edges.add((next(iter(a)), next(iter(b))))

    declared, active_links = set(), []
    for link in links:
        if link.get("status", "live") == "future":
            continue
        a, b = link["from"], link["to"]
        if a not in active or b not in active:
            continue
        def app_for(oid):
            cur, seen = oid, set()
            while cur in objects and cur not in seen:
                seen.add(cur)
                if objects[cur]["kind"] == "app": return cur
                cur = objects[cur].get("parent")
            return oid
        pair = (app_for(a), app_for(b))
        if pair[0] != pair[1]:
            declared.add(pair); active_links.append((link["id"], pair))

    undeclared = sorted(app_edges - declared)
    missing = sorted((lid, pair) for lid, pair in active_links if pair not in app_edges)
    unowned = sorted(tracked_code - owned_files)
    stale = []
    for oid, ents in expanded.items():
        for entry, files in ents.items():
            if not files:
                stale.append({"object": oid, "entry": entry})
    return {"project": project, "root": str(root), "undeclared_edges": [{"from": a, "to": b} for a, b in undeclared],
            "declared_without_code_edge": [{"link": lid, "from": a, "to": b} for lid, (a, b) in missing],
            "unowned_files": unowned, "stale_owns": stale,
            "stats": {"tracked_code_files": len(tracked_code), "code_import_edges": len(code_edges), "app_edges": len(app_edges)}}


def report(c, project, json_out=False, fail_on_undeclared=False):
    try:
        result = analyze(c, project)
    except (ValueError, OSError) as e:
        print(f"ERROR {e}")
        return 1
    if json_out:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"C4 drift: {project} ({result['stats']['tracked_code_files']} tracked code files, {result['stats']['code_import_edges']} import edges)")
        for key, label in (("undeclared_edges", "undeclared code edges"), ("declared_without_code_edge", "declared links without code edges"), ("unowned_files", "unowned tracked code files"), ("stale_owns", "owns entries matching nothing")):
            print(f"{label}: {len(result[key])}")
            for row in result[key]:
                if key == "undeclared_edges": line = f"{row['from']} -> {row['to']}"
                elif key == "declared_without_code_edge": line = f"{row['link']}: {row['from']} -> {row['to']}"
                else: line = row if isinstance(row, str) else f"{row['object']}: {row['entry']}"
                print("  " + line)
    return 1 if fail_on_undeclared and result["undeclared_edges"] else 0
