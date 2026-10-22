"""Layered C4 folder: map.yaml + contracts/ + behavior/ + flows/ <-> DB (design: docs/research/c4-layered-map-format.yaml)."""
import ast, json, os, pathlib, re
import yaml
from strata import symbols

STATUS = {"live", "future", "doing", "maintenance", "deprecated", "removed"}
KINDS = {"actor", "system", "app", "store", "component", "group"}
KEYS = {"objects": {"id", "parent", "kind", "name", "summary", "status", "tags", "owns", "behavior"},
        "links": {"id", "from", "to", "name", "summary", "detail", "status"},
        "contracts": {"id", "transport", "body", "start", "end"},
        "flows": {"id", "name", "steps"},
        "steps": {"link", "reverse", "values", "text", "at", "transition"}}
class _Loader(yaml.SafeLoader): pass  # YAML 1.1 reads `on:` as True; behavior files use `on:` as a key, so only true/false are booleans
_Loader.yaml_implicit_resolvers = {k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:bool"] for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))
j = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None
dump = lambda path, data: path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def ancestors(byid, id):
    """(parent ids above `id`, bad): bad is the id where the chain hits a cycle or a missing id, else None."""
    seen, out, p = {id}, [], (byid.get(id) or {}).get("parent")
    while p is not None and isinstance(p, str):
        if p in seen or p not in byid: return out, p
        seen.add(p); out.append(p); p = byid[p].get("parent")
    return out, None


def step_ends(s, conns, objs):
    """(start, end) of a flow step and an error text or None. Step forms: {connection, reverse?} | {at}; reverse walks the link backwards."""
    if not isinstance(s, dict): return None, "bước phải là object"
    has_c, has_at = s.get("connection") is not None, s.get("at") is not None
    if has_c + has_at != 1: return None, "cần đúng một trong connection | at"
    if s.get("reverse") and not has_c: return None, "reverse chỉ dùng với connection"
    if has_at:
        return ((s["at"], s["at"]), None) if s["at"] in objs else (None, f"at '{s['at']}' không tồn tại")
    c = conns.get(s["connection"])
    if c is None: return None, f"connection '{s['connection']}' không tồn tại"
    a, b = c.get("from"), c.get("to")
    return ((b, a) if s.get("reverse") else (a, b)), None


def _related(objs, a, b):
    """a == b or one is an ancestor of the other."""
    def up(x):
        seen = []
        while x is not None and x not in seen: seen.append(x); x = (objs.get(x) or {}).get("parent")
        return seen
    return a in up(b) or b in up(a)



def _read(path, errs):
    try: return yaml.load(path.read_text(encoding="utf-8"), _Loader)
    except (yaml.YAMLError, OSError) as e:
        errs.append(f"{path.name}: không đọc được ({getattr(e, 'problem', e)})")


def _keys(errs, where, r, sec):
    if not isinstance(r, dict): errs.append(f"{where}: phải là mapping"); return False
    bad = [k for k in r if k not in KEYS[sec]]
    if bad: errs.append(f"{where}: key lạ {bad}")
    return True


def load(d):
    """(model, errs) from a folder. model = {project:{id?,name?,root}, objects, links, contracts, behavior:{module: data}, flows}."""
    d = pathlib.Path(d); errs = []
    mp = d / "map.yaml"
    if not mp.is_file(): return None, [f"thiếu {mp}"]
    raw = _read(mp, errs) or {}
    if not isinstance(raw, dict): return None, errs + ["map.yaml phải là mapping"]
    for k in raw.keys() - {"project", "objects", "links"}: errs.append(f"map.yaml: key lạ '{k}'")
    pr = raw.get("project")
    m = {"project": pr if isinstance(pr, dict) else {"name": pr} if pr else {}, "contracts": [], "behavior": {}, "flows": []}
    m["project"].setdefault("root", ".")
    for sec in ("objects", "links"):
        rows = raw.get(sec) or []
        m[sec] = [r for i, r in enumerate(rows, 1) if _keys(errs, f"{sec} #{i} ({r.get('id') if isinstance(r, dict) else r})", r, sec)] if isinstance(rows, list) else errs.append(f"{sec}: phải là list") or []
    for f in sorted((d / "contracts").glob("*.yaml")):
        rows = _read(f, errs) or []
        if not isinstance(rows, list): errs.append(f"{f.name}: phải là list"); continue
        for r in rows:
            if _keys(errs, f"contract {f.stem}.{r.get('id') if isinstance(r, dict) else r}", r, "contracts"):
                if not r.get("id"): errs.append(f"contracts/{f.name}: entry thiếu id")
                m["contracts"].append({**r, "id": f"{f.stem}.{r.get('id')}"})
    for f in sorted((d / "behavior").glob("*.yaml")):
        data = _read(f, errs)
        if isinstance(data, dict) and data.get("module", f.stem) == f.stem: m["behavior"][f.stem] = data
        else: errs.append(f"behavior/{f.name}: phải là mapping, module = tên file")
    for f in sorted((d / "flows").glob("*.yaml")):
        r = _read(f, errs)
        if not _keys(errs, f"flows/{f.name}", r, "flows"): continue
        if r.get("id", f.stem) != f.stem: errs.append(f"flows/{f.name}: id '{r.get('id')}' khác tên file")
        for i, s in enumerate(r.get("steps") or [], 1): _keys(errs, f"flow {f.stem} bước {i}", s, "steps")
        m["flows"].append({**r, "id": f.stem})
    return m, errs


def _dup(errs, kind, ids):
    for i in {x for x in ids if ids.count(x) > 1}: errs.append(f"trùng id {kind}: {i}")


def resolve(sym, root, cache, idx=None):
    """None if `path::Qual.name` is defined in a Python file, else a warning text. idx = (symbol cache conn, project): used when fresh, else direct ast."""
    path, sep, qual = sym.partition("::")
    if not sep or not qual: return "sai dạng path::Qual.name"
    f = symbols.inside(root, path)
    if f is None: return f"{path}: ngoài root"
    if not f.is_file(): return f"chưa resolve: không có file {path}"
    if f.suffix != ".py": return f"chưa resolve: {f.suffix or path} không phải Python"
    if idx and (hit := symbols.resolves(idx[0], idx[1], root, sym)) is not None: return None if hit else f"chưa resolve: {path} không có {qual}"
    if f not in cache:
        try: cache[f] = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, OSError): cache[f] = None
    node = cache[f]
    if node is None: return f"chưa resolve: {path} không parse được"
    for name in qual.split("."):
        node = next((n for n in getattr(node, "body", []) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
        if node is None: return f"chưa resolve: {path} không có {qual}"


def check(m, d, idx=None):
    """(errs, warns, stats) of a loaded model; d is the folder (code root = project.root relative to it); idx as in resolve."""
    errs, warns = [], []
    root = (pathlib.Path(d) / m["project"]["root"]).resolve()
    objs, links, cons = {}, {}, {r.get("id"): r for r in m["contracts"]}
    for sec, rows, ids in (("object", m["objects"], objs), ("link", m["links"], links)):
        _dup(errs, sec, [r.get("id") for r in rows])
        for r in rows:
            if not r.get("id"): errs.append(f"{sec} thiếu id")
            ids[r.get("id")] = r
    _dup(errs, "contract", [r.get("id") for r in m["contracts"]])
    for oid, o in objs.items():
        if not o.get("name"): errs.append(f"{oid}: thiếu name")
        if o.get("kind") not in KINDS: errs.append(f"{oid}: kind '{o.get('kind')}' không hợp lệ")
        if o.get("status", "live") not in STATUS: errs.append(f"{oid}: status sai")
        p = o.get("parent")
        if p is not None and p not in objs: errs.append(f"{oid}: parent '{p}' không tồn tại")
        elif p is not None and ancestors(objs, oid)[1] in objs: errs.append(f"{oid}: chuỗi parent bị vòng")
        b = o.get("behavior")
        if b is not None and pathlib.PurePath(str(b)).stem not in m["behavior"]: errs.append(f"{oid}: behavior '{b}' không có file")
    for mod in m["behavior"]:
        if mod not in objs: errs.append(f"behavior/{mod}.yaml: không có object '{mod}'")
    for lid, x in links.items():
        for end in ("from", "to"):
            if x.get(end) not in objs: errs.append(f"link {lid}: {end} '{x.get(end)}' không tồn tại")
        if x.get("detail") is not None and x["detail"] not in cons: errs.append(f"link {lid}: detail '{x['detail']}' không tồn tại")
        if x.get("status", "live") not in STATUS: errs.append(f"link {lid}: status sai")
    cache = {}
    for cid, r in cons.items():
        if not isinstance(cid, str) or "." not in cid or cid.endswith("."): errs.append(f"contract {cid}: thiếu id"); continue
        st, en = r.get("start"), r.get("end")
        if not isinstance(en, str) or not (isinstance(st, str) or isinstance(st, list) and all(isinstance(s, str) for s in st)):
            errs.append(f"contract {cid}: start (chuỗi hoặc list) và end (chuỗi) bắt buộc"); continue
        for sym in [*([st] if isinstance(st, str) else st), en]:
            if w := resolve(sym, root, cache, idx): warns.append(f"contract {cid}: {sym}: {w}")
    flat = {k: {"from": x.get("from"), "to": x.get("to")} for k, x in links.items()}
    for f in m["flows"]:
        prev = None
        for i, s in enumerate(f.get("steps") or [], 1):
            where = f"flow {f['id']} bước {i}"
            if not isinstance(s, dict): errs.append(f"{where}: phải là mapping"); continue
            if s.get("link") is not None and s["link"] not in links: errs.append(f"{where}: link '{s['link']}' không tồn tại"); continue
            ends, err = step_ends({**{k: v for k, v in s.items() if k in ("at", "reverse")}, **({"connection": s["link"]} if "link" in s else {})}, flat, objs)
            if err: errs.append(f"{where}: {err.replace('connection', 'link')}"); continue
            if s.get("transition") is not None:
                beh = m["behavior"].get(pathlib.PurePath(str(objs[s["at"]].get("behavior") or "")).stem) if "at" in s else None
                if "at" not in s: errs.append(f"{where}: transition chỉ dùng với at")
                elif s["transition"] not in [t.get("id") for t in (beh or {}).get("transitions") or [] if isinstance(t, dict)]:
                    warns.append(f"{where}: transition '{s['transition']}' chưa có trong behavior của '{s['at']}'")
            if ends and prev and not _related(objs, prev[1], ends[0]):
                warns.append(f"{where}: đứt mạch, bắt đầu ở '{ends[0]}' nhưng bước trước kết thúc ở '{prev[1]}'")
            prev = ends or prev
    n = sum(x.get("detail") is not None for x in links.values())
    return errs, warns, {"object": len(objs), "link": len(links), "contract": len(cons), "behavior": len(m["behavior"]), "flow": len(m["flows"]), "detail": n}


def report(d, idx=None):
    m, errs = load(d)
    warns, st = [], None
    if m is not None: e2, warns, st = check(m, d, idx); errs += e2
    for w in warns: print("WARN ", w)
    for e in errs: print("ERROR", e)
    if st: print(f"{st['object']} object, {st['link']} link, {st['contract']} contract, {st['behavior']} behavior, {st['flow']} flow; {st['detail']}/{st['link']} link có detail — {len(errs)} lỗi, {len(warns)} cảnh báo")
    return 1 if errs else 0


def _counts(c, project):
    return {t: c.execute(f"SELECT count(*) FROM c4_{t} WHERE project=?", (project,)).fetchone()[0] for t in ("object", "connection", "flow", "contract", "behavior")}


def _upsert(c, table, pk, row):
    cols = ",".join(row)
    c.execute(f"INSERT INTO c4_{table}({cols}) VALUES({','.join('?' * len(row))}) ON CONFLICT({pk}) DO UPDATE SET "
              + ",".join(f"{k}=excluded.{k}" for k in row if k not in pk.split(",")), tuple(row.values()))


def _rows(m, project):
    """{table: {key: row}} the folder would write (key = the table's id column)."""
    return {
        "object": {o["id"]: {"id": o["id"], "project": project, "type": o.get("kind"), "name": o.get("name"), "parent": o.get("parent"),
                             "description": o.get("summary"), "tags": j(o.get("tags")), "status": o.get("status"), "owns": j(o.get("owns")), "behavior": o.get("behavior")} for o in m["objects"]},
        "connection": {x["id"]: {"id": x["id"], "project": project, "from_id": x.get("from"), "to_id": x.get("to"), "name": x.get("name"),
                                 "description": x.get("summary"), "detail": x.get("detail"), "status": x.get("status")} for x in m["links"]},
        "contract": {r["id"]: {"project": project, "id": r["id"], "transport": r.get("transport"), "body": j(r.get("body")),
                               "start": j(r.get("start")), "end_sym": r.get("end")} for r in m["contracts"]},
        "behavior": {mod: {"project": project, "module": mod, "form": d.get("form"), "data": j(d)} for mod, d in m["behavior"].items()},
        "flow": {x["id"]: {"id": x["id"], "project": project, "name": x.get("name"), "steps": j(x.get("steps"))} for x in m["flows"]}}


_PK = {"object": "id", "connection": "id", "contract": "id", "behavior": "module", "flow": "id"}


def diff_model(c, m, project):
    """What importing model `m` would change: {table: {added, changed, removed: [ids]}} (table 'link' = connection) + 'dropped_links' (task links of vanished objects)."""
    new, out = _rows(m, project), {}
    for t, pk in _PK.items():
        old = {r[pk]: dict(r) for r in c.execute(f"SELECT * FROM c4_{t} WHERE project=?", (project,))}
        out["link" if t == "connection" else t] = {
            "added": [k for k in new[t] if k not in old], "removed": [k for k in old if k not in new[t]],
            "changed": [k for k, r in new[t].items() if k in old and any(old[k].get(f) != v for f, v in r.items())]}
    gone = [r for r in c.execute("SELECT object_id,ref_kind,ref_id FROM c4_link WHERE project=?", (project,)) if r["object_id"] not in new["object"]]
    out["dropped_links"] = [{"object": r["object_id"], "kind": r["ref_kind"], "id": r["ref_id"],
                             "title": (c.execute("SELECT title FROM item WHERE id=?", (r["ref_id"],)).fetchone() or [None])[0]} for r in gone]
    return out


def _dropped_text(df):
    return "\n".join(f"  {x['kind']} #{x['id']} {x['title'] or ''} (object {x['object']})" for x in df["dropped_links"])


def diff_text(df):
    lines = []
    for t, v in df.items():
        if t == "dropped_links": continue
        lines.append(f"{t}: +{len(v['added'])} ~{len(v['changed'])} -{len(v['removed'])}")
        lines += [f"  {s} {i}" for s, k in (("+", "added"), ("~", "changed"), ("-", "removed")) for i in v[k]]
    if df["dropped_links"]: lines.append("dropped task links:\n" + _dropped_text(df))
    return "\n".join(lines)


def import_dir(c, d, project, force=False, dry_run=False, yes=False):
    """Audited upsert of a layered folder into `project`; rows absent from the folder are deleted, and task links to objects that no longer exist. Atomic.
    Returns the new counts, or the diff when dry_run. Refuses (ValueError) when links would be dropped and not `yes`."""
    m, errs = load(d)
    if m is not None: errs += check(m, d)[0]
    if errs and not force: raise ValueError("model có lỗi, không ghi gì (--force để bỏ qua):\n" + "\n".join(errs))
    if m is None: raise ValueError(errs[0])
    df = diff_model(c, m, project)
    if dry_run: return df
    if df["dropped_links"] and not yes:
        raise ValueError("import sẽ mất link task, không ghi gì (--yes để chấp nhận):\n" + _dropped_text(df))
    pr, new = m["project"], _rows(m, project)
    with c:
        before = _counts(c, project)
        _upsert(c, "meta", "project", {"project": project, "name": pr.get("name") or pr.get("id") or project,
                                       "root": str((pathlib.Path(d) / pr["root"]).resolve()), "source": str(pathlib.Path(d).resolve())})
        for t, pk in _PK.items():
            for row in new[t].values(): _upsert(c, t, "project," + pk, row)
            keep = list(new[t])
            c.execute(f"DELETE FROM c4_{t} WHERE project=? AND {pk} NOT IN ({','.join('?' * len(keep))})", (project, *keep))
        c.execute("DELETE FROM c4_link WHERE project=? AND object_id NOT IN (SELECT id FROM c4_object WHERE project=?)", (project, project))
        after = _counts(c, project)
        c.execute("INSERT INTO audit(project,actor_role,tool,target,before,after) VALUES(?,?,?,?,?,?)",
                  (project, "cli", "c4-import", str(d), j(before), j({"counts": after, "diff": df})))
    return after


def export_dir(c, project, d):
    """Write the DB model back as a layered folder (same shape import_dir reads)."""
    d = pathlib.Path(d)
    meta = c.execute("SELECT * FROM c4_meta WHERE project=?", (project,)).fetchone()
    if not meta: raise KeyError(f"project {project!r} chưa import")
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,)).fetchall()
    jl = lambda v: json.loads(v) if v is not None else None
    keep = lambda **kw: {k: v for k, v in kw.items() if v is not None}
    for sub in ("contracts", "behavior", "flows"): (d / sub).mkdir(parents=True, exist_ok=True)
    dump(d / "map.yaml", {
        "project": keep(id=project, name=meta["name"], root=pathlib.Path(os.path.relpath(meta["root"] or d.resolve(), d.resolve())).as_posix()),
        "objects": [keep(id=o["id"], parent=o["parent"], kind=o["type"], name=o["name"], summary=o["description"], status=o["status"],
                         tags=jl(o["tags"]), owns=jl(o["owns"]), behavior=o["behavior"]) for o in q("object")],
        "links": [keep(id=x["id"], **{"from": x["from_id"]}, to=x["to_id"], name=x["name"], summary=x["description"], detail=x["detail"], status=x["status"]) for x in q("connection")]})
    files = {}
    for r in q("contract"):
        stem, _, eid = r["id"].partition(".")
        files.setdefault(stem, []).append(keep(id=eid, transport=r["transport"], body=jl(r["body"]), start=jl(r["start"]), end=r["end_sym"]))
    for stem, rows in files.items(): dump(d / "contracts" / f"{stem}.yaml", rows)
    for r in q("behavior"): dump(d / "behavior" / f"{r['module']}.yaml", jl(r["data"]))
    for r in q("flow"): dump(d / "flows" / f"{r['id']}.yaml", keep(id=r["id"], name=r["name"], steps=jl(r["steps"])))


# ---- read side: text for agents (c4 flow / context / contract) ----

def read_model(c, project):
    """{name, root, objects, connections, flows} for the viewer and /code, or None when the project has no imported map."""
    meta = c.execute("SELECT * FROM c4_meta WHERE project=?", (project,)).fetchone()
    if not meta: return None
    jl = lambda v: json.loads(v) if v is not None else None
    clean = lambda d: {k: v for k, v in d.items() if v is not None}
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,)).fetchall()
    return {"name": meta["name"], "root": meta["root"],
            "objects": [clean({"id": o["id"], "type": o["type"], "name": o["name"], "parent": o["parent"], "description": o["description"],
                               "tags": jl(o["tags"]), "status": o["status"], "owns": jl(o["owns"]), "behavior": o["behavior"]}) for o in q("object")],
            "connections": [clean({"id": x["id"], "from": x["from_id"], "to": x["to_id"], "name": x["name"], "description": x["description"],
                                   "detail": x["detail"], "status": x["status"]}) for x in q("connection")],
            "flows": [clean({"id": f["id"], "name": f["name"], "steps": jl(f["steps"]) or []}) for f in q("flow")]}


def viewer_extra(c, project):
    """Extra /api/c4 fields for a layered project: contracts {id: {transport, body, start, end}} and behavior {module: data}."""
    jl = lambda v: json.loads(v) if v is not None else None
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,)).fetchall()
    return {"layered": True,
            "contracts": {r["id"]: {k: v for k, v in {"transport": r["transport"], "body": jl(r["body"]), "start": jl(r["start"]), "end": r["end_sym"]}.items() if v is not None} for r in q("contract")},
            "behavior": {r["module"]: jl(r["data"]) for r in q("behavior")}}


def _model(c, project):
    q = lambda t: c.execute(f"SELECT * FROM c4_{t} WHERE project=? ORDER BY rowid", (project,)).fetchall()
    return {"objects": {o["id"]: o for o in q("object")}, "links": {x["id"]: x for x in q("connection")},
            "contracts": {r["id"]: r for r in q("contract")}, "behavior": {r["module"]: r for r in q("behavior")}, "flows": q("flow")}


def _ends(r):
    """'start → end' of a contract row ('?' when a side is missing)."""
    s = json.loads(r["start"]) if r["start"] else None
    return f"{', '.join(s) if isinstance(s, list) else s or '?'} → {r['end_sym'] or '?'}"


def flow_text(c, project, flow=None):
    m = _model(c, project)
    if flow is None:
        return "\n".join(f"{f['id']}  {len(json.loads(f['steps'] or '[]'))} bước  {f['name'] or ''}" for f in m["flows"]) or "(không có flow)"
    f = next((x for x in m["flows"] if x["id"] == flow), None)
    if f is None: raise ValueError(f"không có flow '{flow}' trong project '{project}'")
    steps = json.loads(f["steps"] or "[]")
    nm = lambda i: (m["objects"].get(i) or {"name": i})["name"] or i
    out = [f"# {f['id']}: {f['name'] or ''} ({len(steps)} bước)"]
    for n, s in enumerate(steps, 1):
        if s.get("at"):
            ln = f"{n}. @ {nm(s['at'])}" + (f" (transition {s['transition']})" if s.get("transition") else "")
            out.append(ln + (f" {s['text']}" if s.get("text") else "")); continue
        x = m["links"].get(s.get("link"))
        if x is None: out.append(f"{n}. ?? link '{s.get('link')}' không tồn tại"); continue
        a, b = (x["to_id"], x["from_id"]) if s.get("reverse") else (x["from_id"], x["to_id"])
        ln = f"{n}. {nm(a)} → {nm(b)} [{x['name'] or x['id']}{' ↩' if s.get('reverse') else ''}]"
        if s.get("text"): ln += f" {s['text']}"
        if s.get("values"): ln += " | " + ", ".join(f"{k}={v}" for k, v in s["values"].items())
        out.append(ln)
        r = m["contracts"].get(x["detail"]) if x["detail"] else None
        if r:
            e = _ends(r)
            if s.get("reverse"): e = " → ".join(reversed(e.split(" → ")))
            out.append(f"   ↳ {e}")
    return "\n".join(out)


def contract_text(c, project, id):
    r = c.execute("SELECT * FROM c4_contract WHERE project=? AND id=?", (project, id)).fetchone()
    if not r: raise ValueError(f"không có contract '{id}' trong project '{project}'")
    out = [f"# {r['id']}" + (f": {r['transport']}" if r["transport"] else "")]
    for k, v in (json.loads(r["body"]) if r["body"] else {}).items(): out.append(f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v}")
    out.append(f"start → end: {_ends(r)}")
    return "\n".join(out)


def context_text(c, project, object=None, max_tokens=2000):
    from strata import db
    m = _model(c, project); objs = m["objects"]
    label = lambda o: f"{o['id']} [{o['type']}] {o['name'] or ''}"
    kids = lambda p: [o for o in objs.values() if o["parent"] == p]
    if object is None:
        out = [f"# {project}: {len(objs)} object, {len(m['links'])} link, {len(m['flows'])} flow"]
        def walk(p, d):
            for o in kids(p): out.append("  " * d + "- " + label(o)); walk(o["id"], d + 1)
        walk(None, 0)
        out += ["", "Flow (xem: c4 flow --id F):"] + [f"- {f['id']} ({len(json.loads(f['steps'] or '[]'))} bước): {f['name'] or ''}" for f in m["flows"]]
        out += ["", "Link:"] + [f"- {x['id']}: {x['from_id']}→{x['to_id']} {x['name'] or ''}" + (" +detail" if x["detail"] else "") for x in m["links"].values()]
    else:
        o = objs.get(object)
        if o is None: raise ValueError(f"không có object '{object}' trong project '{project}'")
        out = [f"# {label(o)}"] + ([f"Mô tả: {o['description']}"] if o["description"] else [])
        if o["parent"]: out.append(f"Cha: {o['parent']}")
        if kids(object): out += ["Con:"] + [f"- {label(k)}" for k in kids(object)]
        if o["owns"]: out.append("Owns: " + ", ".join(json.loads(o["owns"])))
        b = m["behavior"].get(o["behavior"]) if o["behavior"] else None
        if b:
            d = json.loads(b["data"]); out.append(f"Behavior {b['module']}: {b['form'] or '-'}, {len(d.get('states') or [])} state, {len(d.get('transitions') or [])} transition")
        out.append("Link:")
        for x in m["links"].values():
            if object not in (x["from_id"], x["to_id"]): continue
            out.append(f"- {x['id']}: {x['from_id']}→{x['to_id']} {x['name'] or ''}")
            r = m["contracts"].get(x["detail"]) if x["detail"] else None
            if r: out += [f"    {r['transport'] or '-'}", f"    {_ends(r)}"]
        lk = db.links_for(c, project, object)
        rel = [f"- {i['kind']} #{i['id']} [{i['status']}] {i['title']}" for i in lk["items"]]
        if rel: out += ["Liên quan:"] + rel
        def touches(s):
            x = m["links"].get(s.get("link"))
            return s.get("at") == object or (x is not None and object in (x["from_id"], x["to_id"]))
        out += ["Flow:"] + [f"- {f['id']}: {f['name'] or ''}" for f in m["flows"] if any(touches(s) for s in json.loads(f["steps"] or "[]"))]
    t = "\n".join(out)
    return t if len(t) // 4 <= max_tokens else t[:max_tokens * 4] + "\n... (cắt; dùng --max-tokens lớn hơn)"
