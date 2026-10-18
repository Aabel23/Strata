"""C4 model: YAML import into the DB, and validation (from a YAML file or from the DB)."""
import json, pathlib
import yaml

TYPES = {"actor", "system", "app", "store", "component", "group"}
STATUS = {"live", "future", "deprecated", "removed"}
# Which parent types each type may sit under (None = top level).
PARENTS = {"actor": {None, "group"}, "system": {None, "group"}, "group": {None, "group", "system", "app"},
           "app": {"system", "group"}, "store": {"system", "group"}, "component": {"app", "group"}}


def load(path):
    model = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    root = (pathlib.Path(path).resolve().parent / model.get("root", ".")).resolve()
    return model, root


def check(m, root):
    """Return (errors, warnings, n_objects, n_connections) for a model dict."""
    errs, warns = [], []
    objs = {}
    for o in m.get("objects", []):
        if o.get("id") in objs: errs.append(f"trùng id: {o.get('id')}")
        objs[o.get("id")] = o
    for o in objs.values():
        t, p = o.get("type"), o.get("parent")
        if t not in TYPES: errs.append(f"{o['id']}: type '{t}' không hợp lệ")
        if p is not None and p not in objs: errs.append(f"{o['id']}: parent '{p}' không tồn tại")
        elif t in PARENTS and (objs[p]["type"] if p else None) not in PARENTS[t]:
            errs.append(f"{o['id']}: {t} không được nằm trong {objs[p]['type'] if p else 'top level'}")
        if o.get("status", "live") not in STATUS: errs.append(f"{o['id']}: status sai")
        for t2 in o.get("tags", []):
            if t2 not in (m.get("tags") or {}): warns.append(f"{o['id']}: tag '{t2}' chưa khai báo")
        for link in o.get("links", []):
            if not link.startswith("http") and not (root / link).exists():
                errs.append(f"{o['id']}: link chết '{link}'")
        if not o.get("description"): warns.append(f"{o['id']}: thiếu description")
    used = set()
    conns = {c.get("id", f"c{i}"): c for i, c in enumerate(m.get("connections", []))}
    for cid, c in conns.items():
        for end in ("from", "to"):
            if c.get(end) not in objs: errs.append(f"connection {cid}: {end} '{c.get(end)}' không tồn tại")
            used.add(c.get(end))
        if not c.get("technology"): warns.append(f"connection {cid} ({c.get('from')}→{c.get('to')}): thiếu technology")
    for f in m.get("flows", []):
        for i, s in enumerate(f.get("steps", []), 1):
            ok = s.get("connection") in conns or any(c.get("from") == s.get("from") and c.get("to") == s.get("to") for c in conns.values())
            if not ok: errs.append(f"flow {f.get('id')} bước {i}: không khớp connection nào")
    parents = {o.get("parent") for o in objs.values()}
    for oid in objs:
        if oid not in used and oid not in parents: warns.append(f"{oid}: không có kết nối nào")
    return errs, warns, len(objs), len(conns)


def report(m, root):
    errs, warns, no, nc = check(m, root)
    for w in warns: print("WARN ", w)
    for e in errs: print("ERROR", e)
    print(f"{no} object, {nc} connection, {len(m.get('flows', []))} flow — {len(errs)} lỗi, {len(warns)} cảnh báo")
    return 1 if errs else 0


def validate_file(path):
    return report(*load(path))


def validate_db(c, project):
    m = read_model(c, project)
    if m is None:
        print(f"ERROR project '{project}' chưa import"); return 1
    return report(m, pathlib.Path(m["root"] or "."))


def _counts(c, project):
    return {t: c.execute(f"SELECT count(*) FROM c4_{t} WHERE project=?", (project,)).fetchone()[0]
            for t in ("object", "connection", "flow")}


def import_yaml(c, path, project):
    """Upsert the YAML model into project `project`; rows absent from the YAML are deleted. Atomic."""
    m, root = load(path)
    objs = m.get("objects") or []
    conns = [{**x, "id": x.get("id", f"c{i}")} for i, x in enumerate(m.get("connections") or [])]
    flows = m.get("flows") or []
    for kind, rows in (("object", objs), ("connection", conns), ("flow", flows)):
        ids = [r.get("id") for r in rows]
        if None in ids or len(set(ids)) != len(ids): raise ValueError(f"{kind}: thiếu hoặc trùng id")
    j = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None
    with c:
        before = _counts(c, project)
        c.execute("INSERT INTO c4_meta VALUES(?,?,?,?,?) ON CONFLICT(project) DO UPDATE SET name=excluded.name,"
                  "root=excluded.root,layout=excluded.layout,tags=excluded.tags",
                  (project, m.get("name") or project, str(root), m.get("layout"), j(m.get("tags"))))
        for o in objs:
            c.execute("INSERT INTO c4_object(id,project,type,name,parent,technology,description,tags,links,status) VALUES(?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET type=excluded.type,name=excluded.name,parent=excluded.parent,"
                      "technology=excluded.technology,description=excluded.description,tags=excluded.tags,links=excluded.links,status=excluded.status",
                      (o["id"], project, o.get("type"), o.get("name"), o.get("parent"), o.get("technology"),
                       o.get("description"), j(o.get("tags")), j(o.get("links")), o.get("status")))
        for x in conns:
            c.execute("INSERT INTO c4_connection(id,project,from_id,to_id,name,technology,status,direction,tags,description) VALUES(?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET from_id=excluded.from_id,to_id=excluded.to_id,name=excluded.name,"
                      "technology=excluded.technology,status=excluded.status,direction=excluded.direction,tags=excluded.tags,description=excluded.description",
                      (x["id"], project, x.get("from"), x.get("to"), x.get("name"), x.get("technology"),
                       x.get("status"), x.get("direction"), j(x.get("tags")), x.get("description")))
        for f in flows:
            c.execute("INSERT INTO c4_flow(id,project,name,steps) VALUES(?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET name=excluded.name,steps=excluded.steps",
                      (f["id"], project, f.get("name"), j(f.get("steps"))))
        for t, rows in (("object", objs), ("connection", conns), ("flow", flows)):
            keep = [r["id"] for r in rows]
            c.execute(f"DELETE FROM c4_{t} WHERE project=? AND id NOT IN ({','.join('?' * len(keep))})", (project, *keep))
        after = _counts(c, project)
        c.execute("INSERT INTO audit(project,actor_role,tool,target,before,after) VALUES(?,?,?,?,?,?)",
                  (project, "cli", "import-yaml", str(path), j(before), j(after)))
    return after


def _row(r, renames=(), jsons=()):
    d = dict(r); d.pop("project", None)
    for k, v in renames: d[v] = d.pop(k)
    for k in jsons:
        if d.get(k) is not None: d[k] = json.loads(d[k])
    return {k: v for k, v in d.items() if v is not None}


def read_model(c, project):
    """The model dict (same shape as the YAML) or None if the project was never imported."""
    meta = c.execute("SELECT * FROM c4_meta WHERE project=?", (project,)).fetchone()
    if not meta: return None
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,))
    return {**_row(meta, jsons=("tags",)), "root": meta["root"],
            "objects": [_row(r, jsons=("tags", "links")) for r in q("object")],
            "connections": [_row(r, (("from_id", "from"), ("to_id", "to")), ("tags",)) for r in q("connection")],
            "flows": [_row(r, jsons=("steps",)) for r in q("flow")]}
