"""One structured edit of a layered C4 folder: validate, write files, re-import (design: ticket #238)."""
import copy, re, unicodedata
from strata import c4_layered as L

_OBJ = {"name": str, "kind": str, "parent": str, "summary": str, "tech": str, "status": str, "owns": list, "tags": list}
_LNK = {"name": str, "summary": str, "detail": str, "status": str, "from": str, "to": str}


def _typed(d, spec, where, allow=()):
    """ValueError unless d is a dict whose keys are in spec (+allow) and whose values have the spec type (owns/tags: list of str)."""
    if not isinstance(d, dict): raise ValueError(f"{where} must be an object")
    bad = sorted(set(d) - set(spec) - set(allow))
    if bad: raise ValueError(f"{where}: unknown keys {bad}")
    for k, v in d.items():
        t = spec.get(k, str)
        if v is None: continue
        if not isinstance(v, t) or (t is list and not all(isinstance(x, str) for x in v)):
            raise ValueError(f"{where}: '{k}' must be {'a list of strings' if t is list else 'an object' if t is dict else 'a boolean' if t is bool else 'a string'}")


def _need(op, key):
    if not op.get(key): raise ValueError(f"{op['op']}: '{key}' is required")
    return op[key]


def _find(rows, id, what):
    for r in rows:
        if r.get("id") == id: return r
    raise ValueError(f"unknown {what} '{id}'")


def _slug(text, taken):
    s = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).strip("_") or "object"
    out, n = s, 2
    while out in taken: out, n = f"{s}_{n}", n + 1
    return out


def _set(row, vals):
    for k, v in vals.items():
        if v is None: row.pop(k, None)
        else: row[k] = v


def _flow_refs(m, links=(), objs=()):
    """Names of flows with a step on one of these link / object ids."""
    return sorted({f["id"] for f in m["flows"] for s in f.get("steps") or [] if isinstance(s, dict) and (s.get("link") in links or s.get("at") in objs)})


def _add_object(m, op):
    _typed(op, _OBJ, "add_object", ("op", "id"))
    name = _need(op, "name"); kind = _need(op, "kind")
    if kind not in L.KINDS: raise ValueError(f"add_object: kind '{kind}' not in {sorted(L.KINDS)}")
    ids = [o.get("id") for o in m["objects"]]
    oid = op.get("id") or _slug(name, ids)
    if not isinstance(oid, str): raise ValueError("add_object: 'id' must be a string")
    if oid in ids: raise ValueError(f"duplicate object id '{oid}'")
    if op.get("parent") is not None and op["parent"] not in ids: raise ValueError(f"unknown parent '{op['parent']}'")
    m["objects"].append({"id": oid, **{k: v for k, v in op.items() if k not in ("op", "id") and v is not None}})


def _update_object(m, op):
    _typed(op, {"set": dict}, "update_object", ("op", "id"))
    o = _find(m["objects"], _need(op, "id"), "object")
    if "id" in (op.get("set") or {}): raise ValueError("update_object: renaming the id is not allowed")
    _typed(op.get("set"), _OBJ, "update_object set")
    _set(o, op["set"])


def _delete_object(m, op):
    _typed(op, {"cascade": bool}, "delete_object", ("op", "id"))
    oid = _need(op, "id"); _find(m["objects"], oid, "object")
    ids, todo = {oid}, [oid]
    while todo:
        p = todo.pop()
        for o in m["objects"]:
            if o.get("parent") == p and o["id"] not in ids: ids.add(o["id"]); todo.append(o["id"])
    links = [x["id"] for x in m["links"] if x.get("from") in ids or x.get("to") in ids]
    if (len(ids) > 1 or links) and not op.get("cascade"):
        raise ValueError(f"object '{oid}' has {len(ids) - 1} descendants and {len(links)} links; use cascade to delete them too")
    if fl := _flow_refs(m, links, ids): raise ValueError(f"cannot delete '{oid}': used by flow(s) {', '.join(fl)}")
    stems = {oid_ for oid_ in ids} | {L.pathlib.PurePath(str(o["behavior"])).stem for o in m["objects"] if o["id"] in ids and o.get("behavior")}
    m["objects"] = [o for o in m["objects"] if o["id"] not in ids]
    m["links"] = [x for x in m["links"] if x["id"] not in links]
    for s in stems: m["behavior"].pop(s, None)


def _add_link(m, op):
    _typed(op, _LNK, "add_link", ("op", "id"))
    a, b, name = _need(op, "from"), _need(op, "to"), _need(op, "name")
    ids = {o.get("id") for o in m["objects"]}
    for e in (a, b):
        if e not in ids: raise ValueError(f"unknown object '{e}'")
    if op.get("detail") is not None and op["detail"] not in [c["id"] for c in m["contracts"]]: raise ValueError(f"unknown contract '{op['detail']}'")
    taken = [x.get("id") for x in m["links"]]
    lid = op.get("id") or _slug(f"{a}_{b}", taken)
    if not isinstance(lid, str): raise ValueError("add_link: 'id' must be a string")
    if lid in taken: raise ValueError(f"duplicate link id '{lid}'")
    m["links"].append({"id": lid, **{k: v for k, v in op.items() if k not in ("op", "id") and v is not None}})


def _update_link(m, op):
    _typed(op, {"set": dict}, "update_link", ("op", "id"))
    x = _find(m["links"], _need(op, "id"), "link")
    _typed(op.get("set"), _LNK, "update_link set")
    ids = {o.get("id") for o in m["objects"]}
    for e in ("from", "to"):
        if op["set"].get(e) is not None and op["set"][e] not in ids: raise ValueError(f"unknown object '{op['set'][e]}'")
    if op["set"].get("detail") is not None and op["set"]["detail"] not in [c["id"] for c in m["contracts"]]: raise ValueError(f"unknown contract '{op['set']['detail']}'")
    _set(x, op["set"])


def _delete_link(m, op):
    _typed(op, {}, "delete_link", ("op", "id"))
    lid = _need(op, "id"); _find(m["links"], lid, "link")
    if fl := _flow_refs(m, [lid]): raise ValueError(f"cannot delete link '{lid}': used by flow(s) {', '.join(fl)}")
    m["links"] = [x for x in m["links"] if x["id"] != lid]


_OPS = {f.__name__[1:]: f for f in (_add_object, _update_object, _delete_object, _add_link, _update_link, _delete_link)}
_key = lambda f: (f["id"], f["subject"], f["message"])


def apply(c, project, op, yes=False):
    """Apply one op to the project's C4 folder, write it, re-import. Returns {"ok", "changed", "warnings"}; ValueError leaves files and DB as they were."""
    row = c.execute("SELECT source FROM c4_meta WHERE project=?", (project,)).fetchone()
    if not row or not row["source"]: raise KeyError(f"project {project!r} has no imported C4 map")
    folder = row["source"]
    m, errs = L.load(folder)
    if m is None: raise ValueError(L.fmt(errs[0]))
    if not isinstance(op, dict) or op.get("op") not in _OPS: raise ValueError(f"unknown op {op.get('op') if isinstance(op, dict) else op!r}; use one of {sorted(_OPS)}")
    e0, w0, _ = L.check(m, folder)
    before = {_key(f) for f in errs + e0}
    old, new = copy.deepcopy(m), copy.deepcopy(m)
    _OPS[op["op"]](new, op)
    e1, w1, _ = L.check(new, folder)
    fresh = [f for f in e1 if _key(f) not in before]
    if fresh: raise ValueError("the edit introduces errors:\n" + "\n".join(map(L.fmt, fresh)))
    df = L.diff_model(c, new, project)
    if df["dropped_links"] and not yes: raise ValueError("the edit would drop task links (pass yes to accept):\n" + L._dropped_text(df))
    changed = L.write_model(new, folder)
    try: L.import_dir(c, folder, project, yes=yes)
    except Exception:
        L.write_model(old, folder); raise
    seen = {_key(f) for f in w0}
    return {"ok": True, "changed": changed, "warnings": [L.fmt(f) for f in w1 if _key(f) not in seen]}
