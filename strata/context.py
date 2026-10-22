"""task context: one budgeted text bundle for a coder (decisions 11, 28)."""
import json, pathlib, re, sys
from strata import c4_layered, service


def _rules(root):
    """The '## Luật cứng' section of root/CLAUDE.md, or None."""
    try: t = (pathlib.Path(root) / "CLAUDE.md").read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError): return None
    m = re.search(r"^## Luật cứng\s*\n(.*?)(?=^## |\Z)", t, re.S | re.M)
    return "## Luật cứng\n" + m.group(1).strip() if m else None


def build(c, item_id, budget=12000):
    i = service.get_item(c, item_id); spec = i.get("spec") or {}
    warn = []
    tk = [f"# Ticket #{i['id']} [{i['status']}] {i['title']}"]
    for k in ("goal", "acceptance", "verify", "scope", "open_questions"):
        if spec.get(k): tk.append(f"{k}: {json.dumps(spec[k], ensure_ascii=False)}")
    tk += [f"depends_on #{d['id']} [{d['status']}] {d['title']}" for d in i["depends_on"]]
    if not spec and i["body"]: tk.append(i["body"])
    objs = [r[0] for r in c.execute("SELECT object_id FROM c4_link WHERE project=? AND ref_kind='item' AND ref_id=? ORDER BY object_id", (i["project"], item_id))]
    ids = {r[0] for o in objs for r in c.execute("SELECT ref_id FROM c4_link WHERE project=? AND ref_kind='decision' AND object_id=?", (i["project"], o))}
    ids |= {int(n) for n in re.findall(r"decision\s+#?(\d+)", json.dumps(spec, ensure_ascii=False), re.I)}
    dec = [f"#{d['id']} {d['title']} — {(d['decision'] or '')[:160]}" for d in
           (c.execute("SELECT id,title,decision FROM decision WHERE project=? AND id=?", (i["project"], n)).fetchone() for n in sorted(ids)) if d]
    root = (c.execute("SELECT root FROM project WHERE id=?", (i["project"],)).fetchone() or [None])[0]
    rules = _rules(root)
    if rules is None: warn.append("CLAUDE.md '## Luật cứng' missing, skipped")
    touch = (spec.get("scope") or {}).get("touch") or []
    secs = [("ticket", "\n".join(tk)), ("hard rules", rules), ("decisions", "## Decisions\n" + "\n".join(dec) if dec else None)]
    out, used = [], 0
    for name, t in secs:
        if not t: continue
        room = budget - used - (2 if out else 0)
        if len(t) <= room: out.append(t); used += len(t) + (2 if len(out) > 1 else 0)
        elif name == "ticket": out.append(t[:max(room, 0)]); used = budget; warn.append("ticket truncated")
        else: warn.append(f"cut {name}")
    left = budget - used - 2
    for n, o in enumerate(objs):
        share = left // (len(objs) - n)
        try: t = f"## C4 {o}\n" + c4_layered.context_text(c, i["project"], o)
        except (ValueError, KeyError) as e: warn.append(f"c4 {o}: {e}"); continue
        if share < 80: warn.append(f"cut c4 {o}"); continue
        if len(t) > share: t = t[:share]; warn.append(f"truncated c4 {o}")
        out.append(t); left -= len(t) + 2
    if touch:
        t = "## Paths\n" + "\n".join(touch)
        if len(t) <= left: out.append(t); left -= len(t) + 2
        else: warn.append("cut paths")
    if warn: print("context warning: " + "; ".join(warn), file=sys.stderr)
    return "\n\n".join(out)[:budget]
