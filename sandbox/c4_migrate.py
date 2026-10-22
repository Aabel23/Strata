"""N5: convert a project's old C4 map (DB copy) to the layered folder docs/c4/{map.yaml,contracts/,flows/} + report.

    STRATA_DB=COPY.db python3 -I sandbox/c4_migrate.py --db COPY.db --project strata --out docs/c4 --report REPORT.md [--apply-links]
Needs `sym index --project P` done on the same DB first (symbol cache sits next to it). --apply-links rewrites c4_link rows
of the removed objects onto their module (run on the COPY only; the real DB gets the printed SQL via `c4 link/unlink`)."""
import argparse, collections, json, pathlib, sqlite3, sys
import yaml

CODE = {"file", "function"}
OVERRIDE = {"f_rm_template": "strata/roadmap.py::init_template"}  # names that are not identifiers
dump = lambda p, d: p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
js = lambda v: json.loads(v) if isinstance(v, str) and v[:1] in "[{\"" else v


def rows(c, sql, *a): return [dict(r) for r in c.execute(sql, a)]


def convert(db, project, out, report):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    sc = sqlite3.connect(pathlib.Path(db).with_name(pathlib.Path(db).stem + ".symbols.db")); sc.row_factory = sqlite3.Row
    meta = rows(c, "select * from c4_meta where project=?", project)[0]
    objs = {o["id"]: o for o in rows(c, "select * from c4_object where project=?", project)}
    conns = rows(c, "select * from c4_connection where project=? order by rowid", project)
    ifs = {i["id"]: i for i in rows(c, "select * from c4_interface where project=?", project)}
    rep = collections.defaultdict(list)  # section -> [(id, outcome, note)]

    def module(oid):
        o = objs.get(oid)
        while o and o["type"] in CODE: o = objs.get(o["parent"])
        return o["id"] if o else None

    def files(o):
        while o:
            if fs := js(o["links"]): return fs
            o = objs.get(o["parent"]) if o["type"] in CODE else None
        return []

    def symbol(o):
        """(symbol id, resolved?) for a function object; unresolved ones are kept as `path::name`."""
        fs, name = files(o), o["name"].strip()
        if o["id"] in OVERRIDE: return OVERRIDE[o["id"]], True
        for f in fs:
            hits = [r["id"] for r in sc.execute("select id from symbol where project=? and file=? and (id=? or id like ?)", (project, f, f"{f}::{name}", f"{f}::%.{name}"))]
            if len(hits) == 1: return hits[0], True
        return f"{fs[0] if fs else '?'}::{name}", False

    sym = {}
    for o in objs.values():
        if o["type"] == "function":
            sym[o["id"], ] = None
            s, ok = symbol(o); sym[o["id"]] = s
            rep["functions"].append((o["id"], "replaced" if ok else "unresolved", s))
        elif o["type"] == "file": rep["files"].append((o["id"], "replaced", f"owns of {module(o['id'])}"))
    sym = {k: v for k, v in sym.items() if isinstance(k, str)}

    # objects L1-L3 (kind = old type; summary = description; owns = old links paths)
    new_objs = []
    for o in objs.values():
        if o["type"] in CODE: continue
        n = {"id": o["id"], "parent": o["parent"], "kind": o["type"], "name": o["name"], "summary": o["description"], "status": o["status"],
             "tags": js(o["tags"]), "owns": js(o["links"]) if o["type"] in ("app", "store", "component", "group") else None}
        new_objs.append({k: v for k, v in n.items() if v}); rep["objects"].append((o["id"], "kept", ""))

    # connections -> links (+ contract when both ends were functions); intra-module calls dropped
    links, contracts, cmap = {}, collections.defaultdict(dict), {}  # cmap: conn id -> link id | ("internal", module)
    for k in conns:
        f, t = k["from_id"], k["to_id"]; fm, tm = module(f), module(t)
        if fm == tm and (f in sym or t in sym or objs[f]["type"] in CODE or objs[t]["type"] in CODE):
            cmap[k["id"]] = ("internal", fm); rep["connections"].append((k["id"], "replaced", f"intra-module call in {fm}")); continue
        both = f in sym and t in sym
        key = (fm, tm, sym[t]) if both else (fm, tm, k["name"])
        lifted = (fm, tm) != (f, t)
        if key not in links:
            ifc = ifs.get(k["interface"]) or {}
            body = {kk: v for kk, v in {"signature": ifc.get("signature"), "purpose": ifc.get("purpose"), "request": ifc.get("input"), "response": ifc.get("output"),
                    "errors": js(ifc.get("errors")), "payload": js(k["payload"])}.items() if v}
            links[key] = {"id": k["id"], "from": fm, "to": tm, "name": k["name"], "summary": k["description"], "status": k["status"],
                          "_starts": [], "_t": k["technology"] or k["kind"], "_body": body, "_end": sym[t] if both else None}
        L = links[key]
        if both:
            if sym[f] not in L["_starts"]: L["_starts"].append(sym[f])
        elif lifted:  # a mixed endpoint has no pair of symbols: keep the function symbol in the summary
            s = " ".join(x for x in [L["summary"], "[code: " + " → ".join(x for x in (sym.get(f), sym.get(t)) if x) + "]"] if x)
            L["summary"] = s
        cmap[k["id"]] = L["id"]
        rep["connections"].append((k["id"], "replaced" if lifted else "kept", f"{fm}→{tm}" + (f" merged into {L['id']}" if L["id"] != k["id"] else "")))
    out_links = []
    for L in links.values():
        if L["_end"]:
            L["detail"] = f"{L['to']}.{L['id']}"
            contracts[L["to"]][L["id"]] = {k: v for k, v in {"id": L["id"], "transport": L["_t"], "body": L["_body"],
                                         "start": L["_starts"][0] if len(L["_starts"]) == 1 else L["_starts"], "end": L["_end"]}.items() if v}
        out_links.append({k: v for k, v in L.items() if not k.startswith("_") and v})

    # flows
    byid = {l["id"]: l for l in out_links}
    flows = []
    for fl in rows(c, "select * from c4_flow where project=?", project):
        steps = []
        for i, s in enumerate(js(fl["steps"]) or [], 1):
            sid = f"{fl['id']}#{i}"
            if "connection" in s:
                m = cmap.get(s["connection"])
                if isinstance(m, tuple):
                    f = objs[next(k for k in conns if k["id"] == s["connection"])["from_id"]]
                    steps.append({"at": m[1], "text": s.get("text") or f"{f['name']} calls within {objs[m[1]]['name']}"}); rep["flow steps"].append((sid, "replaced", f"at {m[1]}"))
                elif m:
                    steps.append({k: v for k, v in {"link": m, "reverse": s.get("reverse"), "text": s.get("text"), "values": s.get("payload")}.items() if v}); rep["flow steps"].append((sid, "kept", ""))
                else: rep["flow steps"].append((sid, "unresolved", f"connection {s['connection']} gone"))
            else:
                a = module(s["at"]); o = objs[s["at"]]
                t = s.get("text"); t = f"{o['name']}: {t}" if o["type"] in CODE and t else t
                steps.append({k: v for k, v in {"at": a, "text": t}.items() if v}); rep["flow steps"].append((sid, "kept" if a == s["at"] else "replaced", f"at {a}"))
        flows.append({"id": fl["id"], "name": fl["name"], "steps": steps})

    # c4_link (item/decision) on removed objects -> module
    moves = []
    for l in rows(c, "select * from c4_link where project=?", project):
        if l["object_id"] in objs and objs[l["object_id"]]["type"] in CODE:
            moves.append((l, module(l["object_id"]))); rep["item links"].append((f"{l['object_id']}:{l['ref_kind']}#{l['ref_id']}", "replaced", module(l["object_id"])))
        else: rep["item links"].append((f"{l['object_id']}:{l['ref_kind']}#{l['ref_id']}", "kept", ""))

    out = pathlib.Path(out)
    for sub in ("contracts", "flows"): (out / sub).mkdir(parents=True, exist_ok=True)
    dump(out / "map.yaml", {"project": {"id": project, "name": meta["name"], "root": "../.."}, "objects": new_objs, "links": out_links})
    for mod, es in contracts.items(): dump(out / "contracts" / f"{mod}.yaml", list(es.values()))
    for f in flows: dump(out / "flows" / f"{f['id']}.yaml", f)

    txt = [f"# N5 migration report: {project}", "", "| Section | kept | replaced | unresolved |", "|---|---|---|---|"]
    for sec, items in rep.items():
        n = collections.Counter(o for _, o, _ in items); txt.append(f"| {sec} | {n['kept']} | {n['replaced']} | {n['unresolved']} |")
    txt += ["", f"Output: {len(new_objs)} objects, {len(out_links)} links, {sum(len(v) for v in contracts.values())} contract entries in {len(contracts)} files, {len(flows)} flows.",
            "", "## Unresolved function symbols (kept as written; validate warns)", *[f"- `{i}` -> `{n}`" for i, o, n in rep["functions"] if o == "unresolved"],
            "", "## c4_link moves (removed object -> module)", *[f"- {l['object_id']} -> {m}: {l['ref_kind']} #{l['ref_id']}" for l, m in moves]]
    pathlib.Path(report).write_text("\n".join(txt) + "\n", encoding="utf-8")
    return moves, c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for a in ("--db", "--project", "--out", "--report"): ap.add_argument(a, required=True)
    ap.add_argument("--apply-links", action="store_true")
    a = ap.parse_args()
    moves, c = convert(a.db, a.project, a.out, a.report)
    for l, m in moves:
        print(f"item/decision {l['ref_kind']} #{l['ref_id']}: {l['object_id']} -> {m}")
        if a.apply_links:
            with c:
                c.execute("INSERT OR IGNORE INTO c4_link VALUES(?,?,?,?)", (a.project, m, l["ref_kind"], l["ref_id"]))
                c.execute("DELETE FROM c4_link WHERE project=? AND object_id=? AND ref_kind=? AND ref_id=?", (a.project, l["object_id"], l["ref_kind"], l["ref_id"]))
