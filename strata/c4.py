"""C4 model: YAML import into the DB, and validation (from a YAML file or from the DB)."""
import json, os, pathlib
import yaml

TYPES = {"actor", "system", "app", "store", "component", "group", "file", "function"}
IFACE_KINDS = {"http", "function", "queue", "event"}
CONN_KINDS = {"api", "network", "call", "queue"}
STATUS = {"live", "future", "doing", "maintenance", "deprecated", "removed"}
# Which parent types each type may sit under (None = top level).
PARENTS = {"actor": {None, "group"}, "system": {None, "group"}, "group": {None, "group", "system", "app"},
           "app": {"system", "group"}, "store": {"system", "group"}, "component": {"app", "group"},
           "file": {"component", "file"}, "function": {"component", "file"}}


KEYS = {
    "objects": {"id", "type", "name", "parent", "technology", "description", "tags", "links", "status", "responsibilities", "state", "interfaces", "kind", "ports"},  # nested contracts
    "ports": {"id", "name", "direction", "kind", "schema"},
    "connections": {"id", "from", "to", "name", "technology", "status", "direction", "tags", "description", "feature", "interface", "payload", "kind", "from_port", "to_port"},
    "interfaces": {"id", "object", "kind", "name", "signature", "purpose", "input", "output", "errors"},
    "flows": {"id", "name", "steps"},
    "steps": {"id", "connection", "at", "from", "to", "text", "payload", "interface", "reverse"}}


def load(path):
    try: model = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        mk = getattr(e, "problem_mark", None)
        raise ValueError(f"YAML sai cú pháp{f' dòng {mk.line + 1} cột {mk.column + 1}' if mk else ''}: "
                         f"{getattr(e, 'problem', e)} (chuỗi có : ? # {{ }} , thì bọc \"...\")") from None
    if not isinstance(model, dict): raise ValueError("YAML phải là mapping ở top level")
    root = (pathlib.Path(path).resolve().parent / model.get("root", ".")).resolve()
    return model, root


def ancestors(byid, id):
    """(parent ids above `id`, bad): bad is the id where the chain hits a cycle or a missing id, else None."""
    seen, out, p = {id}, [], (byid.get(id) or {}).get("parent")
    while p is not None and isinstance(p, str):
        if p in seen or p not in byid: return out, p
        seen.add(p); out.append(p); p = byid[p].get("parent")
    return out, None


def _dups(errs, kind, rows):
    seen = set()
    for r in rows:
        if r.get("id") in seen: errs.append(f"trùng id {kind}: {r.get('id')}")
        seen.add(r.get("id"))


def check(m, root):
    """Return (errors, warnings, n_objects, n_connections) for a model dict."""
    errs, warns = [], []
    if not isinstance(m, dict): return ["YAML phải là mapping ở top level"], warns, 0, 0
    # Unquoted ", " inside a flow mapping silently becomes an extra key: flag any unknown key.
    for sec, keys in KEYS.items():
        rows = m.get(sec) or []
        if sec == "ports": rows = [(f"object {o.get('id')} port {p.get('id')}", p) for o in m.get("objects") or [] if isinstance(o, dict) for p in o.get("ports") or [] if isinstance(p, dict)]
        elif sec == "steps": rows = [(f"flow {f.get('id')} bước {i}", st) for f in m.get("flows") or [] for i, st in enumerate(f.get("steps") or [], 1) if isinstance(st, dict)]
        else: rows = [(f"{sec} {r.get('id')}", r) for r in rows if isinstance(r, dict)]
        for where, r in rows:
            bad = [k for k in r if k not in keys]
            if bad: warns.append(f"{where}: key lạ {bad} (chuỗi có dấu phẩy thì bọc \"...\")")
    objs = {}
    ol = [o for o in m.get("objects") or [] if isinstance(o, dict)]
    for o in ol:
        if o.get("id") in objs: errs.append(f"trùng id: {o.get('id')}")
        objs[o.get("id")] = o
    for o in objs.values():
        t, p = o.get("type"), o.get("parent")
        if not o.get("name"): errs.append(f"{o.get('id')}: thiếu name")
        if p is not None and not isinstance(p, str):
            errs.append(f"{o.get('id')}: parent phải là chuỗi"); continue
        bad = ancestors(objs, o.get("id"))[1]
        if bad in objs: errs.append(f"{o.get('id')}: chuỗi parent bị vòng tại '{bad}'")
        if t not in TYPES: errs.append(f"{o['id']}: type '{t}' không hợp lệ")
        if p is not None and p not in objs: errs.append(f"{o['id']}: parent '{p}' không tồn tại")
        elif bad is None and t in PARENTS and (objs[p]["type"] if p else None) not in PARENTS[t]:
            errs.append(f"{o['id']}: {t} không được nằm trong {objs[p]['type'] if p else 'top level'}")
        if o.get("status", "live") not in STATUS: errs.append(f"{o['id']}: status sai")
        for t2 in o.get("tags") or []:
            if t2 not in (m.get("tags") or {}): warns.append(f"{o['id']}: tag '{t2}' chưa khai báo")
        for link in o.get("links") or []:
            if not link.startswith("http") and not (root / link).exists():
                errs.append(f"{o['id']}: link chết '{link}'")
        if not o.get("description"): warns.append(f"{o['id']}: thiếu description")
    ifaces = {}
    for i in [i for i in m.get("interfaces") or [] if isinstance(i, dict)]:
        if i.get("id") in ifaces: errs.append(f"trùng id interface: {i.get('id')}")
        ifaces[i.get("id")] = i
        if i.get("object") not in objs: errs.append(f"interface {i.get('id')}: object '{i.get('object')}' không tồn tại")
        if i.get("kind") is not None and i["kind"] not in IFACE_KINDS: errs.append(f"interface {i.get('id')}: kind '{i['kind']}' không hợp lệ")
    ports = {}
    for o in ol:
        for p in o.get("ports") or []:
            if not isinstance(p, dict):
                errs.append(f"object {o.get('id')}: port phải là mapping"); continue
            pid = p.get("id")
            if not pid: errs.append(f"object {o.get('id')}: port thiếu id")
            elif pid in ports: errs.append(f"trùng id port: {pid}")
            else: ports[pid] = (o.get("id"), p)
            if p.get("direction") not in ("input", "output"): errs.append(f"port {pid}: direction phải là input hoặc output")
    used = set()
    cl = [c for c in m.get("connections") or [] if isinstance(c, dict)]
    _dups(errs, "connection", [c for c in cl if "id" in c])
    conns = {c.get("id", f"c{i}"): c for i, c in enumerate(cl)}
    for cid, c in conns.items():
        for end in ("from", "to"):
            if c.get(end) not in objs: errs.append(f"connection {cid}: {end} '{c.get(end)}' không tồn tại")
            used.add(c.get(end))
        if c.get("interface") is not None:
            i = ifaces.get(c["interface"])
            if i is None: errs.append(f"connection {cid}: interface '{c['interface']}' không tồn tại")
            elif i.get("object") != c.get("to"): errs.append(f"connection {cid}: interface '{c['interface']}' không thuộc '{c.get('to')}'")
        if c.get("kind") is not None and c["kind"] not in CONN_KINDS: errs.append(f"connection {cid}: kind '{c['kind']}' không hợp lệ")
        for field, end in (("from_port", "from"), ("to_port", "to")):
            pid = c.get(field)
            if pid is not None and (pid not in ports or ports[pid][0] != c.get(end)):
                errs.append(f"connection {cid}: {field} '{pid}' không thuộc object '{c.get(end)}'")
        if not c.get("technology"): warns.append(f"connection {cid} ({c.get('from')}→{c.get('to')}): thiếu technology")
    fl = [f for f in m.get("flows") or [] if isinstance(f, dict)]
    _dups(errs, "flow", fl)
    for f in fl:
        prev = None
        steps = [s for s in f.get("steps") or [] if isinstance(s, dict)]
        _dups(errs, f"step (flow {f.get('id')})", [s for s in steps if "id" in s])
        for i, s in enumerate(steps, 1):
            where = f"flow {f.get('id')} bước {i}"
            ends, err = step_ends(s, conns, objs)
            if err: errs.append(f"{where}: {err}")
            if s.get("interface") is not None and s["interface"] not in ifaces:
                errs.append(f"{where}: interface '{s['interface']}' không tồn tại")
            if ends and prev and not _related(objs, prev[1], ends[0]):
                warns.append(f"{where}: đứt mạch, bắt đầu ở '{ends[0]}' nhưng bước trước kết thúc ở '{prev[1]}'")
            prev = ends or prev
    parents = {o.get("parent") for o in objs.values() if isinstance(o.get("parent"), (str, type(None)))}
    for oid in objs:
        if oid not in used and oid not in parents: warns.append(f"{oid}: không có kết nối nào")
    return errs, warns, len(objs), len(conns)


def step_ends(s, conns, objs):
    """(start, end) of a flow step and an error text or None.

    Step forms: {connection, reverse?} | {at} | legacy {from, to}; plus optional id, text, payload, interface.
    reverse: true walks the connection backwards (to → from), used for responses."""
    if not isinstance(s, dict): return None, "bước phải là object"
    has_c, has_at, has_ft = s.get("connection") is not None, s.get("at") is not None, s.get("from") is not None or s.get("to") is not None
    if has_c + has_at + has_ft != 1: return None, "cần đúng một trong connection | at | from+to"
    if s.get("reverse") and not has_c: return None, "reverse chỉ dùng với connection"
    if has_at:
        return ((s["at"], s["at"]), None) if s["at"] in objs else (None, f"at '{s['at']}' không tồn tại")
    if has_c:
        c = conns.get(s["connection"])
        if c is None: return None, f"connection '{s['connection']}' không tồn tại"
        a, b = c.get("from"), c.get("to")
        return ((b, a) if s.get("reverse") else (a, b)), None
    if any(c.get("from") == s.get("from") and c.get("to") == s.get("to") for c in conns.values()):
        return (s["from"], s["to"]), None
    return None, "không khớp connection nào"


def _related(objs, a, b):
    """a == b or one is an ancestor of the other."""
    def up(x):
        seen = []
        while x is not None and x not in seen: seen.append(x); x = (objs.get(x) or {}).get("parent")
        return seen
    return a in up(b) or b in up(a)


CODE_TYPES = {"app", "component", "file", "function"}


def issues_by_object(m, root):
    """{object id: [codes]} for objects with a problem: dead_link, no_link, no_desc.
    no_link only for code-bearing types; actors, systems, stores, groups need no code link."""
    out = {}
    for o in m.get("objects", []):
        links = o.get("links") or []
        codes = (["dead_link"] if any(not l.startswith("http") and not (root / l).exists() for l in links) else []) \
            + ([] if links or o.get("type") not in CODE_TYPES else ["no_link"]) + ([] if o.get("description") else ["no_desc"])
        if codes: out[o["id"]] = codes
    return out


def report(m, root):
    errs, warns, no, nc = check(m, root)
    for w in warns: print("WARN ", w)
    for e in errs: print("ERROR", e)
    print(f"{no} object, {nc} connection, {len(m.get('flows', []))} flow — {len(errs)} lỗi, {len(warns)} cảnh báo")
    return 1 if errs else 0


def validate_file(path):
    try: return report(*load(path))
    except ValueError as e: print("ERROR", e); return 1


def validate_db(c, project):
    m = read_model(c, project)
    if m is None:
        print(f"ERROR project '{project}' chưa import"); return 1
    return report(m, pathlib.Path(m["root"] or "."))


def _counts(c, project):
    return {t: c.execute(f"SELECT count(*) FROM c4_{t} WHERE project=?", (project,)).fetchone()[0]
            for t in ("object", "connection", "flow")}


def import_yaml(c, path, project, force=False):
    """Upsert the YAML model into project `project`; rows absent from the YAML are deleted. Atomic."""
    m, root = load(path)
    errs = check(m, root)[0]
    if errs and not force: raise ValueError("model có lỗi, không ghi gì (--force để bỏ qua):\n" + "\n".join(errs))
    objs = m.get("objects") or []
    conns = [{**x, "id": x.get("id", f"c{i}")} for i, x in enumerate(m.get("connections") or [])]
    flows = m.get("flows") or []
    ifaces = m.get("interfaces") or []
    ports = [dict(p, object=o["id"]) for o in objs for p in o.get("ports") or []]
    for kind, rows in (("object", objs), ("connection", conns), ("flow", flows), ("interface", ifaces), ("port", ports)):
        ids = [r.get("id") for r in rows]
        if None in ids or len(set(ids)) != len(ids): raise ValueError(f"{kind}: thiếu hoặc trùng id")
    j = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None
    with c:
        before = _counts(c, project)
        c.execute("INSERT INTO c4_meta(project,name,root,layout,tags,source) VALUES(?,?,?,?,?,?) ON CONFLICT(project) DO UPDATE SET name=excluded.name,"
                  "root=excluded.root,layout=excluded.layout,tags=excluded.tags,source=excluded.source",
                  (project, m.get("name") or project, str(root), m.get("layout"), j(m.get("tags")), str(pathlib.Path(path).resolve())))
        for o in objs:
            c.execute("INSERT INTO c4_object(id,project,type,name,parent,technology,description,tags,links,status,responsibilities,state,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET type=excluded.type,name=excluded.name,parent=excluded.parent,"
                      "technology=excluded.technology,description=excluded.description,tags=excluded.tags,links=excluded.links,status=excluded.status,"
                      "responsibilities=excluded.responsibilities,state=excluded.state,kind=excluded.kind",
                      (o["id"], project, o.get("type"), o.get("name"), o.get("parent"), o.get("technology"),
                       o.get("description"), j(o.get("tags")), j(o.get("links")), o.get("status"), j(o.get("responsibilities")), o.get("state"), o.get("kind")))
        for p in ports:
            c.execute("INSERT INTO c4_port(project,id,object_id,name,direction,kind,schema_json) VALUES(?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET object_id=excluded.object_id,name=excluded.name,direction=excluded.direction,kind=excluded.kind,schema_json=excluded.schema_json",
                      (project, p["id"], p["object"], p.get("name"), p.get("direction"), p.get("kind"), j(p.get("schema"))))
        for x in conns:
            c.execute("INSERT INTO c4_connection(id,project,from_id,to_id,name,technology,status,direction,tags,description,feature,interface,payload,kind,from_port_id,to_port_id) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET from_id=excluded.from_id,to_id=excluded.to_id,name=excluded.name,"
                      "technology=excluded.technology,status=excluded.status,direction=excluded.direction,tags=excluded.tags,description=excluded.description,"
                      "feature=excluded.feature,interface=excluded.interface,payload=excluded.payload,kind=excluded.kind,from_port_id=excluded.from_port_id,to_port_id=excluded.to_port_id",
                      (x["id"], project, x.get("from"), x.get("to"), x.get("name"), x.get("technology"),
                       x.get("status"), x.get("direction"), j(x.get("tags")), x.get("description"),
                       x.get("feature"), x.get("interface"), j(x.get("payload")), x.get("kind"), x.get("from_port"), x.get("to_port")))
        for i in ifaces:
            c.execute("INSERT INTO c4_interface(project,id,object_id,kind,name,signature,purpose,input,output,errors) VALUES(?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET object_id=excluded.object_id,kind=excluded.kind,name=excluded.name,"
                      "signature=excluded.signature,purpose=excluded.purpose,input=excluded.input,output=excluded.output,errors=excluded.errors",
                      (project, i["id"], i.get("object"), i.get("kind"), i.get("name"), i.get("signature"),
                       i.get("purpose"), i.get("input"), i.get("output"), j(i.get("errors"))))
        for f in flows:
            c.execute("INSERT INTO c4_flow(id,project,name,steps) VALUES(?,?,?,?) "
                      "ON CONFLICT(project,id) DO UPDATE SET name=excluded.name,steps=excluded.steps",
                      (f["id"], project, f.get("name"), j(f.get("steps"))))
        for t, rows in (("connection", conns), ("flow", flows), ("interface", ifaces), ("port", ports), ("object", objs)):
            keep = [r["id"] for r in rows]
            if t == "port":
                c.execute(f"DELETE FROM c4_port WHERE project=? AND id NOT IN ({','.join('?' * len(keep))})", (project, *keep))
            else:
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
    """The model dict (same shape as the YAML) or None if the project was never imported.

    Shape (keys whose value is NULL are omitted, except `interfaces`, always a list):
      {name, root, layout?, tags?: {tag: {color}}, source?: YAML path,
       objects: [{id, type: actor|system|app|store|component|group|file|function, name, parent?, technology?,
                  description?, tags?: [str], links?: [path|url], status?, responsibilities?: [str], state?: str, kind?: str,
                  interfaces: [{id, object, kind?: http|function|queue|event, name?, signature?, purpose?,
                                input?, output?, errors?: [str]}]}],
       connections: [{id, from, to, name?, technology?, status?, direction?, tags?, description?, from_port?, to_port?,
                      feature?: str, interface?: interface id on `to`, payload?: {request?, response?},
                      kind?: network|call|queue}],
       flows: [{id, name?, steps: [{id?, connection+reverse? | at | from+to, text?, payload?: str, interface?}]}],
       interfaces: [same items as objects[].interfaces, flat]}
    /api/c4 drops root and the flat interfaces list, moves name/layout/tags into meta and adds issues, links, open_issues.
    """
    meta = c.execute("SELECT * FROM c4_meta WHERE project=?", (project,)).fetchone()
    if not meta: return None
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,))
    ifaces = [_row(r, (("object_id", "object"),), ("errors",)) for r in q("interface")]
    objects = [_row(r, jsons=("tags", "links", "responsibilities", "owns")) for r in q("object")]
    ports = [_row(r, (("object_id", "object"),), ("schema_json",)) for r in c.execute("SELECT * FROM c4_port WHERE project=? ORDER BY rowid", (project,))]
    for p in ports:
        if "schema_json" in p: p["schema"] = p.pop("schema_json")
    for o in objects:
        o["interfaces"] = [i for i in ifaces if i["object"] == o["id"]]
        attached = [{k: v for k, v in p.items() if k != "object"} for p in ports if p["object"] == o["id"]]
        if attached: o["ports"] = attached
    connections = [_row(r, (("from_id", "from"), ("to_id", "to"), ("from_port_id", "from_port"), ("to_port_id", "to_port")), ("tags", "payload")) for r in q("connection")]
    result = {**_row(meta, jsons=("tags",)), "root": meta["root"], "objects": objects,
              "connections": connections, "flows": [_row(r, jsons=("steps",)) for r in q("flow")], "interfaces": ifaces}
    result.pop("positions", None)  # legacy column, no longer used
    return result


def export_model(c, project):
    """Return a YAML-ready model in canonical import shape, excluding DB-only fields."""
    m = read_model(c, project)
    if m is None: raise KeyError(f"project {project!r} has no C4 model")
    source = pathlib.Path(m.get("source") or ".").resolve()
    root = pathlib.Path(m.get("root") or ".").resolve()
    m["root"] = pathlib.Path(os.path.relpath(root, source.parent)).as_posix()
    m.pop("source", None); m.pop("project", None)
    m["objects"] = [{k: v for k, v in o.items() if k not in ("interfaces",) and (k != "ports" or v)} for o in m["objects"]]
    if not m.get("tags"): m.pop("tags", None)
    return m


def export_yaml(c, project, path):
    """Export the DB model to a YAML file; root remains anchored to its original absolute path."""
    m = export_model(c, project)
    original_root = pathlib.Path((c.execute("SELECT root FROM c4_meta WHERE project=?", (project,)).fetchone()[0] or ".")).resolve()
    m["root"] = pathlib.Path(os.path.relpath(original_root, pathlib.Path(path).resolve().parent)).as_posix()
    pathlib.Path(path).write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---- text context for agents (port of lift/view in viewer/index.html) ----
def _lift(byid, id, F):
    chain = {F, *ancestors(byid, F)[0]} if F in byid else set()
    for i in [id, *ancestors(byid, id)[0]] if id in byid else []:
        p = byid[i].get("parent")
        if p == F: return i, False
        if p is None or p in chain: return i, True
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
    from strata import c4_layered, db
    if c4_layered.is_layered(c, project): return c4_layered.context_text(c, project, object, max_tokens)
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
        def walk(p, d, deep=True):
            for o in kids(p):
                if not deep and o["type"] in ("file", "function"): continue
                lines.append("  " * d + f"- {o['id']} [{o['type']}] {o.get('name') or ''}" + (f" ({o['technology']})" if o.get("technology") else "")
                             + (f" — {per[o['id']]} issue mở" if per.get(o["id"]) else ""))
                for i in o.get("interfaces") or []:
                    lines.append("  " * d + f"    · {i['id']}: {i.get('signature') or i.get('name') or ''}")
                walk(o["id"], d + 1, deep)
        walk(None, 0)
        if _est("\n".join(lines)) > max_tokens // 2:  # map lớn: bỏ L4 khỏi cây tổng quan
            hidden = sum(o["type"] in ("file", "function") for o in m["objects"])
            del lines[1:]; walk(None, 0, False)
            lines.append(f"... (ẩn {hidden} file/function; dùng --object X)")
        flows = [f"- {f['id']} ({len(f.get('steps') or [])} bước): {f.get('name') or ''}" for f in m["flows"]]
        conns = [f"- {x['from']}→{x['to']}" + (f" [{x['kind']}]" if x.get("kind") else "") + (f" {x['name']}" if x.get("name") else "")
                 + (f" ({x['interface']})" if x.get("interface") else "") for x in m["connections"]]
        out = lines + ["", "Flow (xem: c4 flow --id F):"] + (flows or ["(không)"]) + ["", "Connection:"]
        budget = max_tokens - _est("\n".join(out))
        for k, ln in enumerate(conns):
            if _est(ln) + 1 > budget:
                out.append(f"... (cắt {len(conns) - k} connection; dùng --object X hoặc --max-tokens lớn hơn)"); break
            out.append(ln); budget -= _est(ln) + 1
        return "\n".join(out)
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
    chain = ancestors(byid, object)[0]
    under = lambda i: i == object or object in ancestors(byid, i)[0]
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
            ends = step_ends(s, cmap, byid)[0] or ()
            if any(e in sub for e in ends): flows.append(f"- {f['id']}: {f.get('name') or ''}"); break
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


def _path(byid, i):
    """Readable dotted path: names from the nearest component down (file extensions dropped)."""
    parts, o = [], byid.get(i)
    while o:
        parts.append((o.get("name") or o["id"]).rsplit(".py", 1)[0].rsplit(".dart", 1)[0].rsplit(".kt", 1)[0] if o["type"] == "file" else (o.get("name") or o["id"]))
        if o["type"] not in ("file", "function"): break
        o = byid.get(o.get("parent"))
    parts = [x for k, x in enumerate(reversed(parts)) if k == 0 or x != list(reversed(parts))[k - 1]]
    return ".".join(parts) if parts else i


def flow_text(c, project, flow=None):
    """Numbered one-line-per-step trace of a flow, or the flow list when flow is None."""
    from strata import c4_layered
    if c4_layered.is_layered(c, project): return c4_layered.flow_text(c, project, flow)
    m = read_model(c, project)
    if m is None: raise ValueError(f"project '{project}' chưa import")
    if flow is None:
        return "\n".join(f"{f['id']}  {len(f.get('steps') or [])} bước  {f.get('name') or ''}" for f in m["flows"]) or "(không có flow)"
    f = next((x for x in m["flows"] if x["id"] == flow), None)
    if f is None: raise ValueError(f"không có flow '{flow}' trong project '{project}'")
    byid = {o["id"]: o for o in m["objects"]}
    cmap = {x["id"]: x for x in m["connections"]}
    P = lambda i: _path(byid, i)
    out = [f"# {f['id']}: {f.get('name') or ''} ({len(f.get('steps') or [])} bước)"]
    for n, s in enumerate(f.get("steps") or [], 1):
        ends, err = step_ends(s, cmap, byid)
        if err: out.append(f"{n}. ?? {err}"); continue
        if s.get("at"):
            ln = f"{n}. @ {P(s['at'])}"
        else:
            x = cmap.get(s.get("connection")) or next(v for v in cmap.values() if v.get("from") == s["from"] and v.get("to") == s["to"])
            ln = f"{n}. {P(ends[0])} → {P(ends[1])} [{x.get('kind') or '-'}{' ↩' if s.get('reverse') else ''}]"
            if not s.get("text") and not s.get("reverse") and x.get("name"): ln += f" {x['name']}"
        if s.get("text"): ln += f" {s['text']}"
        if s.get("interface"): ln += f" ({s['interface']})"
        if s.get("payload"): ln += f" | payload: {s['payload']}"
        out.append(ln)
    return "\n".join(out)

