"""Page blocks: exactly 8 types. validate() returns (errors, warnings); page_text() feeds FTS."""
import re

STATUS = ("done", "plan")
KINDS = ("research", "discussion", "note")
# Columns a query block / /api/query may filter on, per source table.
QUERY_COLS = {"item": {"id", "project", "kind", "status", "priority", "scope", "owner", "always_load", "core"},
              "decision": {"id", "project", "status", "supersedes"}}
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
    if src not in QUERY_COLS: return e("src must be item|decision")
    w = b.get("where", {})
    if not _dict(w): return e("'where' must be an object")
    for k, v in w.items():
        if k not in QUERY_COLS[src]: e(f"where column '{k}' not allowed for {src}")
        elif isinstance(v, bool) or not (isinstance(v, int) or _isstr(v)): e(f"where '{k}' must be a non-empty string or an integer")
    if "limit" in b and not (isinstance(b["limit"], int) and not isinstance(b["limit"], bool) and 1 <= b["limit"] <= 200):
        e("limit must be an integer 1..200")

CHECKS = {"md": _md, "layers": _layers, "mermaid": _mermaid, "table": _table, "legend": _legend,
          "question": _question, "c4": _c4, "query": _query}


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
