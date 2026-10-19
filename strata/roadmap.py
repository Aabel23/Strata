"""Roadmap on top of items (decision 27): step = item kind 'step', gate = item kind 'gate' (item_dep on its steps),
content = one page kind 'plan'. Step lifecycle uses the normal item verbs; only import and gate pass write here."""
import hashlib, html.parser, json, pathlib, re
from strata import db, service

PROG_STATUS = {"todo": "approved", "doing": "doing", "review": "review", "done": "done", "blocked": "approved"}
RANK = {"approved": 0, "doing": 1, "review": 2, "done": 3}
RAW_KEYS = {"lead", "body", "intro", "guide", "callout"}  # fields the source page renders as HTML; the rest are escaped text
RAW_LISTS = {"items", "sources"}
PROGRESS_KEYS = ("reviewer", "evidence", "note", "updated")


class _MD(html.parser.HTMLParser):
    """strong/b -> **, code -> `, a -> [t](href), br -> newline; every other tag is dropped, its text kept."""
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.hrefs = []
    def handle_starttag(self, tag, attrs):
        if tag in ("strong", "b"): self.out.append("**")
        elif tag == "code": self.out.append("`")
        elif tag == "br": self.out.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href"); self.hrefs.append(href)
            if href: self.out.append("[")
    def handle_endtag(self, tag):
        if tag in ("strong", "b"): self.out.append("**")
        elif tag == "code": self.out.append("`")
        elif tag == "a" and self.hrefs:
            href = self.hrefs.pop()
            if href: self.out.append("](" + href.replace(" ", "%20").replace("(", "%28").replace(")", "%29") + ")")
    def handle_data(self, d): self.out.append(d)


def html_to_md(s):
    p = _MD(); p.feed(s); p.close()
    return "".join(p.out).strip()


def spec_hash(acceptance, verify=None):
    return hashlib.sha256(json.dumps([acceptance, verify], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _nat(k): return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", k)]


def _convert(v, key=None):
    """Recursively turn the HTML fields of plan.json into markdown."""
    if isinstance(v, str): return html_to_md(v) if key in RAW_KEYS else v
    if isinstance(v, list): return [html_to_md(x) if key in RAW_LISTS and isinstance(x, str) else _convert(x, key) for x in v]
    if isinstance(v, dict): return {k: _convert(x, k) for k, x in v.items()}
    return v


def _load_file(path):
    p = pathlib.Path(path); text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def _phases(plan):
    ph = next((s.get("phases") for s in plan.get("sections", []) if s.get("id") == "chi-tiet"), None)
    if not isinstance(ph, list): raise ValueError("plan: missing section 'chi-tiet' with phases")
    return ph


def _check_inputs(plan, prog):
    if plan.get("version") != 1: raise ValueError("plan: version must be 1")
    ids = [s["id"] for p in _phases(plan) for s in p["steps"]]
    if len(ids) != len(set(ids)): raise ValueError("plan: duplicate step ids")
    for p in _phases(plan):
        n = int(re.sub(r"\D", "", p["anchor"]))
        if any(not s["id"].startswith(f"{n}.") for s in p["steps"]): raise ValueError(f"plan: step ids of {p['anchor']} must start with {n}.")
    extra = set(prog.get("steps", {})) - set(ids)
    if extra: raise ValueError(f"progress: steps not in plan: {sorted(extra, key=_nat)}")
    for k, r in prog.get("steps", {}).items():
        if r.get("status") not in PROG_STATUS: raise ValueError(f"progress {k}: bad status {r.get('status')!r}")
    return ids


def parse_gates(text):
    """'G0=0;G1=1,2' -> {'G0': [0], 'G1': [1, 2]}"""
    try: return {g.strip(): [int(x) for x in ph.split(",")] for g, ph in (part.split("=") for part in text.split(";") if part.strip())}
    except ValueError: raise ValueError(f"bad --gates {text!r}, expected 'G0=0;G1=1,2'")


def _build_page(plan, roadmap, gates):
    page = _convert({k: v for k, v in plan.items() if k != "gates"})
    for sec in page["sections"]:
        for p in sec.get("phases", []):
            p["n"] = int(re.sub(r"\D", "", p["anchor"])); p["steps"] = [s["id"] for s in p["steps"]]
    page["roadmap"] = roadmap
    page["gates"] = [{"id": g, "phases": ph} for g, ph in gates.items()]
    return page


def _map(row):
    """progress.json row -> (status, owner, extras, blocked reason)."""
    st = PROG_STATUS[row["status"]]
    return st, row.get("owner") or None, {k: row.get(k, "") for k in PROGRESS_KEYS}, (row.get("note") or "blocked") if row["status"] == "blocked" else None


def _find(c, project, roadmap, kind, key):
    return c.execute("SELECT * FROM item WHERE project=? AND kind=? AND json_extract(spec,'$.roadmap')=? AND json_extract(spec,'$.step_key')=?",
                     (project, kind, roadmap, key)).fetchone()


def _w(c, project, id, before, after):
    db.audit(c, project, "roadmap.import", f"item:{id}", before, after, "main")


def _upsert(c, project, kind, base, prog_row, st_default="approved"):
    """Create or update one step/gate item. Returns 'created' | 'updated' | 'same'. The only writer of status outside item verbs (tool roadmap.import)."""
    row = _find(c, project, base["roadmap"], kind, base["step_key"])
    mapped = _map(prog_row) if prog_row else (st_default, None, {}, None)
    if row is None:
        status, owner, extras, blocked = mapped
        spec = {**base, **extras, **({"blocked": blocked} if blocked else {})}
        t = db.now(); claimed = (extras.get("updated") or t) if status in ("doing", "review") else None
        cur = c.execute("INSERT INTO item(project,kind,title,body,status,spec,owner,claimed_at,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (project, kind, base["title"], base.get("body"), status, json.dumps(spec, ensure_ascii=False), owner, claimed, "main", t, t))
        i = cur.lastrowid
        _w(c, project, i, None, {"status": status, "owner": owner, "version": 1, "created": True})
        if status == "review":  # imported as already submitted, so `item approve` works on it
            db.audit(c, project, "item.transition", f"item:{i}", {"status": "doing", "owner": owner},
                     {"status": "review", "actor": owner, "note": "imported", "version": 1}, "main")
        return "created", i
    old = json.loads(row["spec"] or "{}"); spec = {**old, **base}; spec.pop("orphan", None)
    status, owner, claimed = row["status"], row["owner"], row["claimed_at"]
    if kind == "step" and status == "done" and old.get("spec_hash") != base["spec_hash"]: spec["stale"] = True
    if prog_row and status != "done" and RANK[mapped[0]] >= RANK[status]:
        status, owner, extras, blocked = mapped; spec.update(extras)
        if blocked: spec["blocked"] = blocked
        else: spec.pop("blocked", None)
        claimed = claimed or ((extras.get("updated") or db.now()) if status in ("doing", "review") else None)
        if status == "approved": claimed = None
    if (base["title"], base.get("body"), spec, status, owner, claimed) == (row["title"], row["body"], old, row["status"], row["owner"], row["claimed_at"]): return "same", row["id"]
    n = c.execute("UPDATE item SET title=?,body=?,status=?,spec=?,owner=?,claimed_at=?,updated_at=?,version=version+1 WHERE id=? AND version=?",
                  (base["title"], base.get("body"), status, json.dumps(spec, ensure_ascii=False), owner, claimed, db.now(), row["id"], row["version"])).rowcount
    if not n: raise RuntimeError("item changed concurrently, retry the import")
    _w(c, project, row["id"], {"status": row["status"], "owner": row["owner"]}, {"status": status, "owner": owner, "version": row["version"] + 1, "stale": spec.get("stale")})
    if status == "review" and row["status"] != "review":
        db.audit(c, project, "item.transition", f"item:{row['id']}", {"status": "doing", "owner": owner},
                 {"status": "review", "actor": owner, "note": "imported", "version": row["version"] + 1}, "main")
    return "updated", row["id"]


def import_plan(c, project, roadmap, plan_file, progress_file=None, gates=None):
    """Upsert steps by step_key (never delete; missing ones become orphan), gates and the 'plan' page. Returns counts."""
    if not c.execute("SELECT 1 FROM project WHERE id=?", (project,)).fetchone(): raise KeyError(f"no project {project}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", roadmap or ""): raise ValueError("bad roadmap id")
    plan = _load_file(plan_file); prog = _load_file(progress_file) if progress_file else {}
    ids = _check_inputs(plan, prog)
    gates = plan.get("gates") or (parse_gates(gates) if gates else {})  # plan key wins over --gates
    if not isinstance(gates, dict) or not all(isinstance(v, list) and all(isinstance(x, int) for x in v) for v in gates.values()): raise ValueError('plan: "gates" must be {"G0": [0], ...}')
    page = _build_page(plan, roadmap, gates); counts = {"created": 0, "updated": 0, "same": 0, "orphan": 0, "gates": 0}
    try:
        keyid = {}
        for p in _phases(plan):
            n = int(re.sub(r"\D", "", p["anchor"]))
            for s in p["steps"]:
                acc = [s["proof"]] if s.get("proof") else []
                base = {"roadmap": roadmap, "phase": n, "step_key": s["id"], "title": s["title"], "body": html_to_md(s.get("body", "")),
                        "proof": s.get("proof", ""), "acceptance": acc, "spec_hash": spec_hash(acc)}
                r, keyid[s["id"]] = _upsert(c, project, "step", base, prog.get("steps", {}).get(s["id"])); counts[r] += 1
        for row in c.execute("SELECT * FROM item WHERE project=? AND kind='step' AND json_extract(spec,'$.roadmap')=?", (project, roadmap)).fetchall():
            sp = json.loads(row["spec"])
            if sp["step_key"] not in keyid and not sp.get("orphan"):
                sp["orphan"] = True
                c.execute("UPDATE item SET spec=?,updated_at=?,version=version+1 WHERE id=?", (json.dumps(sp, ensure_ascii=False), db.now(), row["id"]))
                _w(c, project, row["id"], {"orphan": False}, {"orphan": True, "status": row["status"], "version": row["version"] + 1}); counts["orphan"] += 1
        route = {m.group(0): r for sec in page["sections"] for r in sec.get("route", []) if (m := re.match(r"G\d+", r.get("code", "")))}
        step_phase = {k: int(k.split(".")[0]) for k in keyid}
        for g, phases in gates.items():
            deps = [keyid[k] for k in keyid if step_phase[k] in phases]
            pg = prog.get("gates", {}).get(g); approved = bool(pg and pg.get("approved"))
            if approved and any(c.execute("SELECT status FROM item WHERE id=?", (d,)).fetchone()[0] != "done" for d in deps):
                raise ValueError(f"progress: {g} approved but steps are not done")
            base = {"roadmap": roadmap, "step_key": g, "gate": g, "phases": phases, "title": g + " " + route.get(g, {}).get("title", ""), "body": route.get(g, {}).get("detail")}
            prow = {"status": "done", **{k: pg.get(k, "") for k in PROGRESS_KEYS if k != "note"}} if approved else None
            r, gid = _upsert(c, project, "gate", base, prow); counts["gates"] += r != "same"
            for d in deps: c.execute("INSERT OR IGNORE INTO item_dep VALUES(?,?)", (gid, d))
        for row in c.execute("SELECT id,spec FROM item WHERE project=? AND kind='gate' AND status NOT IN ('done','rejected') AND json_extract(spec,'$.roadmap')=?", (project, roadmap)).fetchall():
            if json.loads(row["spec"])["step_key"] not in gates:
                service.transition(c, "main", row["id"], "rejected", note="gate removed from plan"); counts["gates"] += 1
        db.put_page(c, project, f"roadmap-{roadmap}", page["header"]["title"], "plan", page)
    except Exception: c.rollback(); raise
    return {"steps": len(ids), **counts}


def _load(c, project, roadmap):
    rows = c.execute("SELECT * FROM item WHERE project=? AND kind IN ('step','gate') AND json_extract(spec,'$.roadmap')=? ORDER BY id", (project, roadmap)).fetchall()
    steps, gates = [], []
    for r in rows:
        if r["kind"] == "gate" and r["status"] == "rejected": continue  # removed from plan
        sp = json.loads(r["spec"])
        d = {"id": r["id"], "key": sp["step_key"], "title": r["title"], "body": r["body"], "status": r["status"], "owner": r["owner"], "claimed_at": r["claimed_at"],
             "version": r["version"], "blocked": sp.get("blocked"), "stale": bool(sp.get("stale")), "orphan": bool(sp.get("orphan")),
             **{k: sp.get(k, "") for k in PROGRESS_KEYS}}
        if r["kind"] == "step":
            d.update(phase=sp["phase"], proof=sp.get("proof", ""), acceptance=sp.get("acceptance", []))
            d["state"] = "blocked" if d["blocked"] and d["status"] == "approved" else d["status"]
            steps.append(d)
        else:
            d.update(phases=sp["phases"], gate=sp["gate"], deps=[x[0] for x in c.execute("SELECT depends_on FROM item_dep WHERE item_id=?", (r["id"],))]); gates.append(d)
    steps.sort(key=lambda s: (s["phase"], _nat(s["key"]))); gates.sort(key=lambda g: g["key"])
    by = {s["id"]: s for s in steps}
    for g in gates:
        ds = [by[i] for i in g["deps"] if i in by]; live = [s for s in ds if not s["orphan"]]
        g["done"] = sum(s["status"] == "done" and not s["stale"] for s in live); g["total"] = len(live)
        g["blockers"] = [s["key"] for s in ds if s["status"] != "done" or s["stale"] or s["orphan"]]
        g["ready"] = g["status"] != "done" and not g["blockers"]
    return steps, gates


def _counts(steps, gates):
    live = [s for s in steps if not s["orphan"]]; ph = {}
    for s in live:
        x = ph.setdefault(s["phase"], {"phase": s["phase"], "done": 0, "total": 0}); x["total"] += 1; x["done"] += s["status"] == "done" and not s["stale"]
    return {"done": sum(x["done"] for x in ph.values()), "total": len(live), "phases": [ph[k] for k in sorted(ph)]}


def check(c, project, roadmap):
    steps, gates = _load(c, project, roadmap)
    if not steps: raise KeyError(f"no roadmap {roadmap} in project {project}")
    return {"roadmap": roadmap, "progress": _counts(steps, gates),
            "gates": [{"id": g["key"], "status": g["status"], "done": g["done"], "total": g["total"], "phases": g["phases"], "blockers": g["blockers"]} for g in gates],
            "stale": [s["key"] for s in steps if s["stale"]], "orphan": [s["key"] for s in steps if s["orphan"]],
            "blocked": [{"key": s["key"], "reason": s["blocked"]} for s in steps if s["state"] == "blocked"]}


def check_text(r):
    p = r["progress"]; out = [f"{r['roadmap']}: {p['done']}/{p['total']} steps done"]
    out += [f"  phase {x['phase']}: {x['done']}/{x['total']}" for x in p["phases"]]
    out += [f"  gate {g['id']} (phases {','.join(map(str, g['phases']))}): {g['done']}/{g['total']} [{'passed' if g['status'] == 'done' else 'open'}]" for g in r["gates"]]
    out.append("  stale: " + (", ".join(r["stale"]) or "-")); out.append("  orphan: " + (", ".join(r["orphan"]) or "-"))
    out.append("  blocked: " + ("; ".join(f"{b['key']} ({b['reason']})" for b in r["blocked"]) or "-"))
    return "\n".join(out)


def _refuse(c, project, op, target, info, msg):
    c.rollback(); db.audit(c, project, "denied:" + op, target, None, info, "main"); c.commit(); raise PermissionError(msg)


def gate_pass(c, project, roadmap, gate, actor, evidence=None):
    """User-only: gate -> done when every dependent step is done and neither stale nor orphan."""
    g = _find(c, project, roadmap, "gate", gate)
    if not g: raise KeyError(f"no gate {gate} in roadmap {roadmap}")
    deny = lambda m: _refuse(c, project, "roadmap.gate_pass", f"item:{g['id']}", {"gate": gate, "actor": actor}, m)
    if actor != "user": deny("gate pass needs --as user")
    if g["status"] == "done": deny(f"{gate} already passed")
    steps, gates = _load(c, project, roadmap)
    bad = next(x["blockers"] for x in gates if x["id"] == g["id"])
    if bad: deny(f"{gate} cannot pass: steps not done, stale or orphan: {', '.join(bad)}")
    spec = json.loads(g["spec"]); spec.update(reviewer=actor, updated=db.now()[:10], **({"evidence": evidence} if evidence else {}))
    if not c.execute("UPDATE item SET status='done',spec=?,updated_at=?,version=version+1 WHERE id=? AND version=?",
                     (json.dumps(spec, ensure_ascii=False), db.now(), g["id"], g["version"])).rowcount: deny("gate changed concurrently, retry")
    db.audit(c, project, "roadmap.gate_pass", f"item:{g['id']}", {"status": g["status"]}, {"status": "done", "actor": actor, "evidence": evidence, "version": g["version"] + 1}, "main")
    c.commit()


def reaccept(c, project, roadmap, key, actor):
    """User-only: confirm a stale done step was re-reviewed against its changed acceptance."""
    r = _find(c, project, roadmap, "step", key)
    if not r: raise KeyError(f"no step {key} in roadmap {roadmap}")
    deny = lambda m: _refuse(c, project, "roadmap.reaccept", f"item:{r['id']}", {"step": key, "actor": actor}, m)
    if actor != "user": deny("reaccept needs --as user")
    spec = json.loads(r["spec"])
    if not spec.get("stale"): deny(f"{key} is not stale")
    spec.pop("stale"); spec["updated"] = db.now()[:10]
    c.execute("UPDATE item SET spec=?,updated_at=?,version=version+1 WHERE id=?", (json.dumps(spec, ensure_ascii=False), db.now(), r["id"]))
    db.audit(c, project, "roadmap.reaccept", f"item:{r['id']}", {"stale": True}, {"stale": False, "actor": actor, "version": r["version"] + 1}, "main"); c.commit()


def api(c, project, roadmap=None, only_version=False):
    """GET /api/roadmap: no roadmap = list; else page content + steps + gates (+ version, cheap to poll)."""
    if not roadmap:
        return [{"roadmap": p["slug"][len("roadmap-"):], "title": p["title"], "updated_at": p["updated_at"]} for p in db.list_pages(c, project) if p["kind"] == "plan" and p["slug"].startswith("roadmap-")]
    pg = db.get_page(c, project, f"roadmap-{roadmap}")
    if not pg or pg["kind"] != "plan": return None
    v = c.execute("SELECT max(updated_at),sum(version),count(*) FROM item WHERE project=? AND kind IN ('step','gate') AND json_extract(spec,'$.roadmap')=?", (project, roadmap)).fetchone()
    version = f"{pg['updated_at']}:{v[0]}:{v[1]}:{v[2]}"
    if only_version: return {"version": version}
    steps, gates = _load(c, project, roadmap)
    return {"project": project, "roadmap": roadmap, "title": pg["title"], "updated_at": pg["updated_at"], "version": version, "plan": pg["blocks"],
            "steps": steps, "gates": gates, "progress": _counts(steps, gates)}
