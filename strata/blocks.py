"""Page/doc blocks: 12 types (8 + diagram, swimlane, statemachine, roadmap). validate() returns (errors, warnings); page_text() feeds FTS."""
import re

STATUS = ("done", "plan")
KINDS = ("research", "discussion", "note")
# Columns a query block / /api/query may filter on, per source table.
QUERY_COLS = {"item": {"id", "project", "kind", "status", "priority", "owner", "always_load", "core"}}
SLUG = re.compile(r"^[\w.-]+$")


def page_text(blocks):
    """All human text of the blocks, joined for the FTS index."""
    out = []
    def walk(v):
        if isinstance(v, str): out.append(v)
        elif isinstance(v, list): [walk(x) for x in v]
        elif isinstance(v, dict): [walk(x) for k, x in v.items() if k not in ("type", "status", "src")]
    walk(blocks)
    return "\n".join(out)


def _isstr(v): return isinstance(v, str) and v != ""
def _list(v): return isinstance(v, list)
def _dict(v): return isinstance(v, dict)


def _md(b, e):
    if not _isstr(b.get("text")): e("missing 'text'")

def _layers(b, e):
    if not _list(b.get("rows")): return e("missing 'rows'")
    for i, r in enumerate(b["rows"]):
        if not _dict(r) or not _isstr(r.get("title")): e(f"rows[{i}]: missing 'title'"); continue
        if not _list(r.get("cells")): e(f"rows[{i}]: missing 'cells'"); continue
        for j, c in enumerate(r["cells"]):
            if not _dict(c) or not _isstr(c.get("name")): e(f"rows[{i}].cells[{j}]: missing 'name'")
            elif c.get("status") not in STATUS: e(f"rows[{i}].cells[{j}]: status must be done|plan")
            elif "note" in c and not isinstance(c["note"], str): e(f"rows[{i}].cells[{j}]: 'note' must be text")

def _mermaid(b, e):
    if not _isstr(b.get("code")): e("missing 'code'")

def _table(b, e):
    if not _list(b.get("head")): e("missing 'head'")
    if not _list(b.get("rows")): return e("missing 'rows'")
    for i, r in enumerate(b["rows"]):
        if not _list(r): e(f"rows[{i}]: must be a list")
        elif _list(b.get("head")) and len(r) != len(b["head"]): e(f"rows[{i}]: {len(r)} cells but head has {len(b['head'])}; text with a comma needs quotes")

def _legend(b, e):
    if not _list(b.get("items")): return e("missing 'items'")
    for i, it in enumerate(b["items"]):
        if not _dict(it) or not _isstr(it.get("label")): e(f"items[{i}]: missing 'label'")
        elif it.get("status") not in STATUS: e(f"items[{i}]: status must be done|plan")

def _question(b, e):
    if not _isstr(b.get("q")): e("missing 'q'")
    if not _list(b.get("options")) or not b["options"]: return e("missing 'options'")
    labels = []
    for i, o in enumerate(b["options"]):
        if not _dict(o) or not _isstr(o.get("label")): e(f"options[{i}]: missing 'label'")
        else: labels.append(o["label"])
    if "recommend" in b and b["recommend"] not in labels: e(f"recommend '{b['recommend']}' matches no option label")

def _c4(b, e):
    if not _list(b.get("ids")) or not b["ids"] or not all(_isstr(i) for i in b["ids"]): e("missing 'ids' (non-empty list of ids)")
    if "project" in b and not _isstr(b["project"]): e("'project' must be text")

def _query(b, e):
    src = b.get("src")
    if src not in QUERY_COLS: return e("src must be item")
    w = b.get("where", {})
    if not _dict(w): return e("'where' must be an object")
    for k, v in w.items():
        if k not in QUERY_COLS[src]: e(f"where column '{k}' not allowed for {src}")
        elif isinstance(v, bool) or not (isinstance(v, int) or _isstr(v)): e(f"where '{k}' must be a non-empty string or an integer")
    if "limit" in b and not (isinstance(b["limit"], int) and not isinstance(b["limit"], bool) and 1 <= b["limit"] <= 200):
        e("limit must be an integer 1..200")

def _label(v):
    """Edge/transition label: text, or a list of text lines."""
    return v is None or isinstance(v, str) or (_list(v) and v and all(isinstance(x, str) for x in v))

def _ends(a, ids, name, i, e):
    if len(a) < 2: return e(f"{name}[{i}]: need [from, to, label?]")
    if len(a) > 2 and not _label(a[2]): e(f"{name}[{i}]: label must be text or a list of text")
    for end in a[:2]:
        if end not in ids: e(f"{name}[{i}]: unknown {'node' if name == 'edges' else 'state'} '{end}'")

def _details(v, who, e):
    if v is None: return
    if not (_list(v) and all(_list(r) and len(r) == 2 and all(isinstance(x, str) for x in r) for r in v)):
        e(f"{who}: 'details' must be a list of [label, text] pairs of text")

def _diagram(b, e):
    ns = b.get("nodes")
    if not _list(ns) or not ns: return e("missing 'nodes'")
    ids = set()
    for i, n in enumerate(ns):
        if not _dict(n) or not _isstr(n.get("id")): e(f"nodes[{i}]: missing 'id'"); continue
        if n["id"] in ids: e(f"nodes[{i}]: duplicate id '{n['id']}'")
        ids.add(n["id"])
        for k in ("text", "note", "link", "group"):
            if k in n and not isinstance(n[k], str): e(f"nodes[{i}]: '{k}' must be text")
        _details(n.get("details"), f"nodes[{i}]", e)
        if "shape" in n and n["shape"] not in ("box", "decision", "store"): e(f"nodes[{i}]: shape must be box|decision|store")
        if "tone" in n and n["tone"] not in ("ui", "proc", "store", "ok", "bad", "muted", "warn"): e(f"nodes[{i}]: tone must be ui|proc|store|ok|bad|muted|warn")
    if "dir" in b and b["dir"] not in ("LR", "TB"): e("dir must be LR|TB")
    if "details_title" in b and not isinstance(b["details_title"], str): e("details_title must be text")
    for i, x in enumerate(b.get("edges") or []):
        a = x if _list(x) else [x.get("from"), x.get("to"), x.get("label")] if _dict(x) else []
        _ends(a, ids, "edges", i, e)

def _swimlane(b, e):
    ls = b.get("lanes")
    if _dict(ls) and ls: lanes = [str(x) for v in ls.values() for x in (v if _list(v) else [v])]
    elif _list(ls) and ls: lanes = [str(x) for x in ls]
    else: return e("missing 'lanes' (list, or {zone: [lanes]})")
    ph = b.get("phases", [])
    if not _list(ph): e("'phases' must be a list")
    st = b.get("steps")
    if not _list(st) or not st: return e("missing 'steps'")
    for i, s in enumerate(st):
        w = lambda m: e(f"steps[{i}]: {m}")
        if not _dict(s): w("must be {lane, text}"); continue
        extra = set(s) - {"lane", "text", "phase", "after", "data", "label"}
        if extra: w(f"unknown field {sorted(map(str, extra))}; text with a comma needs quotes")
        if str(s.get("lane")) not in lanes: w(f"lane '{s.get('lane')}' is not in lanes")
        t = s.get("text")
        if not (_isstr(t) or (_list(t) and t and all(_isstr(x) for x in t))): w("missing 'text' (text or list of text)")
        p = s.get("phase")
        if p is not None and not ((isinstance(p, int) and _list(ph) and 1 <= p <= len(ph)) or (_list(ph) and str(p) in map(str, ph))):
            w(f"phase '{p}' matches no phase (number 1..{len(ph) if _list(ph) else 0} or name)")
        for k in ("after", "data"):
            v = s.get(k)
            if v is None: continue
            for n in (v if _list(v) else [v]):
                if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(st) or n == i + 1: w(f"'{k}' step {n} does not exist (steps are numbered 1..{len(st)})")

def _statemachine(b, e):
    ss = b.get("states")
    if not _list(ss) or not ss: return e("missing 'states'")
    ids = set()
    for i, s in enumerate(ss):
        if _isstr(s): s = {"id": s}
        if not _dict(s) or not _isstr(s.get("id")): e(f"states[{i}]: missing 'id'"); continue
        if s["id"] in ids: e(f"states[{i}]: duplicate id '{s['id']}'")
        ids.add(s["id"])
        for k in ("text", "note", "link"):
            if k in s and not isinstance(s[k], str): e(f"states[{i}]: '{k}' must be text")
        _details(s.get("details"), f"states[{i}]", e)
        if "tone" in s and s["tone"] not in ("muted", "ok", "warn", "bad"): e(f"states[{i}]: tone must be muted|ok|warn|bad")
    if "dir" in b and b["dir"] not in ("LR", "TB"): e("dir must be LR|TB")
    if "details_title" in b and not isinstance(b["details_title"], str): e("details_title must be text")
    if "initial_label" in b and not _label(b["initial_label"]): e("initial_label must be text or a list of text")
    if "initial" in b and b["initial"] not in ids: e(f"initial: unknown state '{b['initial']}'")
    fin = b.get("final", [])
    for f in fin if _list(fin) else [fin]:
        if f not in ids: e(f"final: unknown state '{f}'")
    for i, x in enumerate(b.get("transitions") or []):
        a = x if _list(x) else [x.get("from"), x.get("to"), x.get("label")] if _dict(x) else []
        _ends(a, ids, "transitions", i, e)

def _roadmap(b, e):
    ps = b.get("periods")
    if not _list(ps) or not ps: return e("missing 'periods' (non-empty list)")
    ps = [str(p) for p in ps]
    ls = b.get("lanes")
    if ls is not None and not _list(ls): e("'lanes' must be a list")
    ls = [str(x) for x in ls] if _list(ls) else []
    its = b.get("items")
    if not _list(its) or not its: return e("missing 'items'")
    for i, it in enumerate(its):
        w = lambda m: e(f"items[{i}]: {m}")
        if not _dict(it): w("must be {lane?, text, from, to?, status?}"); continue
        if not _isstr(it.get("text")): w("missing 'text'")
        if ls and str(it.get("lane")) not in ls: w(f"lane '{it.get('lane')}' is not in lanes")
        f, t = str(it.get("from")), it.get("to")
        if f not in ps: w(f"from '{it.get('from')}' is not in periods")
        if t is not None and str(t) not in ps: w(f"to '{t}' is not in periods")
        elif t is not None and f in ps and ps.index(str(t)) < ps.index(f): w("'to' is before 'from'")
        if "status" in it and it["status"] not in ("done", "doing", "plan", "blocked"): w("status must be done|doing|plan|blocked")
        if "link" in it and not isinstance(it["link"], str): w("'link' must be text")
    for i, m in enumerate(b.get("milestones") or []):
        if not _dict(m) or not _isstr(m.get("text")): e(f"milestones[{i}]: need {{at, text}}")
        elif str(m.get("at")) not in ps: e(f"milestones[{i}]: at '{m.get('at')}' is not in periods")

CHECKS = {"md": _md, "layers": _layers, "mermaid": _mermaid, "table": _table, "legend": _legend,
          "question": _question, "c4": _c4, "query": _query, "diagram": _diagram, "swimlane": _swimlane,
          "statemachine": _statemachine, "roadmap": _roadmap}

# A doc block may be written short: `- md: "text"`, `- mermaid: "code"`, `- table: {head, rows}`.
SHORT = {"md": "text", "mermaid": "code"}

def normalize(blocks):
    """Doc YAML blocks -> page blocks ({type, ...}). Unknown shapes pass through for validate() to report."""
    out = []
    for b in blocks if _list(blocks) else []:
        if _dict(b) and "type" not in b and len(b) == 1:
            (t, v), = b.items()
            b = {"type": t, SHORT[t]: v} if t in SHORT and isinstance(v, str) else {"type": t, **v} if _dict(v) else {"type": t, "value": v}
        out.append(b)
    return out


def load_doc(src):
    """Parse a doc YAML string -> ({title, summary, code, blocks}, errors)."""
    import yaml
    try: d = yaml.safe_load(src)
    except yaml.YAMLError as x: return {"title": None, "summary": None, "code": [], "blocks": []}, [f"YAML: {x}"]
    if not _dict(d): return {"title": None, "summary": None, "code": [], "blocks": []}, ["doc must be a YAML mapping"]
    code = d.get("code") or []
    code = [code] if isinstance(code, str) else code
    doc = {"title": d.get("title"), "summary": d.get("summary"), "code": code, "blocks": normalize(d.get("blocks"))}
    errs = [] if _isstr(doc["title"]) else ["missing 'title'"]
    if not _list(d.get("blocks")): errs.append("missing 'blocks' (must be a list)")
    if not (_list(code) and all(_isstr(c) for c in code)): errs.append("'code' must be a path or a list of paths")
    if "summary" in d and not isinstance(d["summary"], str): errs.append("'summary' must be text")
    e2, _ = validate(doc["blocks"]); return doc, errs + e2


def validate(blocks, conn=None, project=None):
    """(errors, warnings). With `conn`, c4 ids absent from the DB give a warning (never an error)."""
    errs, warns = [], []
    if not _list(blocks): return ["blocks must be a list"], warns
    for i, b in enumerate(blocks):
        if not _dict(b) or b.get("type") not in CHECKS:
            errs.append(f"block[{i}]: unknown type '{b.get('type') if _dict(b) else b}'"); continue
        n = len(errs)
        CHECKS[b["type"]](b, lambda m: errs.append(f"block[{i}] type {b['type']}: {m}"))
        if b["type"] == "c4" and conn is not None and len(errs) == n:
            p = b.get("project") or project
            have = {r[0] for r in conn.execute("SELECT id FROM c4_object WHERE project=?", (p,))}
            warns += [f"block[{i}] type c4: id '{x}' not in project '{p}'" for x in b["ids"] if x not in have]
    return errs, warns


def validate_doc(doc, conn=None):
    """Validate a whole page document {project, slug, title, kind, blocks}."""
    if not _dict(doc): return ["page file must be a JSON object"], []
    errs = [f"missing '{k}'" for k in ("project", "slug", "title") if not _isstr(doc.get(k))]
    if _isstr(doc.get("slug")) and not SLUG.match(doc["slug"]): errs.append("slug may only contain letters, digits, _ . -")
    if doc.get("kind") not in KINDS: errs.append("kind must be research|discussion|note")
    e2, w = validate(doc.get("blocks"), conn, doc.get("project"))
    return errs + e2, w
