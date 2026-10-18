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


def issues_by_object(m, root):
    """{object id: [codes]} for objects with a problem: dead_link, no_link, no_desc."""
    out = {}
    for o in m.get("objects", []):
        links = o.get("links") or []
        codes = (["dead_link"] if any(not l.startswith("http") and not (root / l).exists() for l in links) else []) \
            + ([] if links else ["no_link"]) + ([] if o.get("description") else ["no_desc"])
        if codes: out[o["id"]] = codes
    return out


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


# ---- text context for agents (port of lift/view in viewer/index.html) ----
def _lift(byid, id, F):
    chain = set()
    o = byid.get(F)
    while o: chain.add(o["id"]); o = byid.get(o.get("parent"))
    o = byid.get(id)
    while o:
        p = o.get("parent")
        if p == F: return o["id"], False
        if p is None or p in chain: return o["id"], True
        o = byid.get(p)
    return None


def _edges(m, F):
    """Merged connections visible when focused on F: {(from,to): [connection]}."""
    byid = {o["id"]: o for o in m["objects"]}
    out = {}
    for c in m["connections"]:
        a, b = _lift(byid, c["from"], F), _lift(byid, c["to"], F)
        if not a or not b or a[0] == b[0] or (a[1] and b[1]): continue
        out.setdefault((a[0], b[0]), []).append(c)
    return out


def _est(s): return len(s) // 4


def context_text(c, project, object=None, max_tokens=2000):
    from strata import db
    m = read_model(c, project)
    if m is None: raise ValueError(f"project '{project}' chưa import")
    byid = {o["id"]: o for o in m["objects"]}
    kids = lambda i: [o for o in m["objects"] if o.get("parent") == i]
    nm = lambda i: byid[i].get("name") or i
    if object is None:
        n = c.execute("SELECT count(*) FROM item WHERE project=? AND kind='issue' AND status NOT IN ('done','rejected')", (project,)).fetchone()[0]
        per = {r[0]: r[1] for r in c.execute("SELECT l.object_id,count(DISTINCT t.id) FROM c4_link l JOIN item t ON t.id=l.ref_id WHERE l.project=? AND l.ref_kind='item' "
                                             "AND t.project=? AND t.kind='issue' AND t.status NOT IN ('done','rejected') GROUP BY l.object_id", (project, project))}
        lines = [f"# {m.get('name') or project} ({project}): {len(byid)} object, {len(m['connections'])} connection, {len(m['flows'])} flow, {n} issue mở"]
        def walk(p, d):
            for o in kids(p):
                lines.append("  " * d + f"- {o['id']} [{o['type']}] {o.get('name') or ''}" + (f" ({o['technology']})" if o.get("technology") else "")
                             + (f" — {per[o['id']]} issue mở" if per.get(o["id"]) else ""))
                walk(o["id"], d + 1)
        walk(None, 0)
        return "\n".join(lines)
    if object not in byid: raise ValueError(f"không có object '{object}' trong project '{project}'")
    o = byid[object]
    def desc(limit=None):
        d = o.get("description") or ""
        return d if limit is None or len(d) <= limit else d[:max(limit - 1, 0)] + "…"
    def head(limit=None):
        s = f"# {o['id']} [{o['type']}] {o.get('name') or ''}"
        if o.get("technology"): s += f"\nTech: {o['technology']}"
        if desc(limit): s += f"\nMô tả: {desc(limit)}"
        if o.get("links"): s += "\nLink: " + ", ".join(o["links"])
        return s
    chain = []
    p = o.get("parent")
    while p: chain.append(p); p = byid[p].get("parent")
    def under(i):
        while i and i != object: i = byid[i].get("parent")
        return i == object
    sub = {i for i in byid if under(i)}
    edges = _edges(m, o.get("parent"))
    conn = []
    for (a, b), cs in edges.items():
        if object not in (a, b): continue
        lbl = f"{len(cs)} kết nối" if len(cs) > 1 else " ".join(x for x in (cs[0].get("name"), f"[{cs[0]['technology']}]" if cs[0].get("technology") else "") if x)
        conn.append(f"- {nm(a)} → {nm(b)}" + (f": {lbl}" if lbl else ""))
    lk = db.links_for(c, project, object)
    rel = [f"- {i['kind']} #{i['id']} [{i['status']}] {i['title']}" for i in lk["items"]] + \
          [f"- decision #{d['id']} [{d['status']}] {d['title']}" for d in lk["decisions"]]
    cmap = {x["id"]: x for x in m["connections"]}
    flows = []
    for f in m["flows"]:
        for s in f.get("steps") or []:
            x = cmap.get(s.get("connection"), s)
            if x.get("from") in sub or x.get("to") in sub: flows.append(f"- {f['id']}: {f.get('name') or ''}"); break
    sections = [  # (name, text): the parent chain stays, the rest drop from the end
        ("chuỗi cha", "Cha: " + " > ".join(nm(i) for i in reversed(chain)) if chain else "Cha: (top level)"),
        ("con trực tiếp", "Con:\n" + "\n".join(f"- {k['id']} [{k['type']}] {k.get('name') or ''}" for k in kids(object)) if kids(object) else "Con: (không)"),
        ("connection", "Connection:\n" + "\n".join(conn) if conn else "Connection: (không)"),
        ("liên quan", "Liên quan:\n" + "\n".join(rel) if rel else "Liên quan: (không)"),
        ("flow", "Flow:\n" + "\n".join(flows) if flows else "Flow: (không)"),
    ]
    keep = len(sections)
    build = lambda h: "\n\n".join([h] + [t if i < keep else f"... (cắt: {n})" for i, (n, t) in enumerate(sections)])
    while _est(build(head())) > max_tokens and keep > 1: keep -= 1
    out = build(head())
    if _est(out) > max_tokens:  # only (1)(2) left: shorten the description
        over = (_est(out) - max_tokens) * 4
        out = build(head(max(len(desc()) - over, 0)))
    return out
