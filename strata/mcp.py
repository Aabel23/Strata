"""MCP server over stdio (JSON-RPC 2.0, one JSON message per line). Role is fixed at launch; clients cannot pass one."""
import json, sys, traceback
from strata import db, service

S = lambda d="": {"type": "string", "description": d}
def schema(props, req): return {"type": "object", "properties": props, "required": req}
TOOLS = {
    "add_item": (service.add_item, "Add a task or issue", schema({"project": S(), "kind": {"type": "string", "enum": ["task", "issue"]}, "title": S(), "body": S(),
                 "priority": S(), "status": {"type": "string", "enum": ["proposed", "approved", "open", "doing", "done", "rejected"]}}, ["project", "kind", "title"])),
    "set_item": (service.set_item, "Change an item's status/priority", schema({"id": {"type": "integer"}, "status": S(), "priority": S()}, ["id"])),
    "add_decision": (service.add_decision, "Record a decision (non-main roles create it as proposed)", schema(
        {k: S() for k in ("project", "title", "context", "decision", "consequences", "rejected")} | {"supersedes": {"type": "integer"}},
        ["project", "title", "context", "decision", "consequences", "rejected"])),
    "set_decision_status": (service.set_decision_status, "Change a decision's status (main only)", schema(
        {"id": {"type": "integer"}, "status": {"type": "string", "enum": ["proposed", "accepted", "superseded"]}}, ["id", "status"])),
    "search": (service.search, "Full-text search over items, decisions, pages and docs", schema(
        {"q": S(), "project": S(), "src": {"type": "string", "enum": ["item", "decision", "page", "doc"]}, "limit": {"type": "integer"}}, ["q"])),
}


def call(c, role, name, args):
    fn, _, sch = TOOLS[name]
    args = {k: v for k, v in args.items() if k in sch["properties"]}  # drops any client-sent role
    for k, v in args.items():
        t = sch["properties"][k].get("type")
        okt = {"string": isinstance(v, str), "integer": type(v) is int and abs(v) < 2**63, "array": isinstance(v, list)}.get(t, True)
        if not okt: raise ValueError(f"argument {k!r} must be {t}")
    out = fn(c, role=role, **args)
    return out if name == "search" else {"ok": True, **({"id": out} if isinstance(out, int) else {})}


def handle(c, role, msg):
    """Returns the response dict, or None for notifications."""
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params")
    ok = lambda r: {"jsonrpc": "2.0", "id": mid, "result": r}
    err = lambda code, m: {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": m}}
    if "id" not in msg: return None
    if p is None: p = {}
    if not isinstance(p, dict): return err(-32602, "params must be an object")
    if method == "initialize":
        return ok({"protocolVersion": p.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}}, "serverInfo": {"name": "strata", "version": "0.1"}})
    if method == "ping": return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, d, s) in TOOLS.items()]})
    if method == "tools/call":
        name, a = p.get("name"), p.get("arguments")
        if a is None: a = {}
        if not isinstance(name, str): return err(-32602, "name must be a string")
        if not isinstance(a, dict): return err(-32602, "arguments must be an object")
        if name not in TOOLS: return err(-32602, f"unknown tool {name}")
        try: text, bad = json.dumps(call(c, role, name, a), ensure_ascii=False), False
        except Exception as e:  # never crash the server on a bad call
            traceback.print_exc(file=sys.stderr); text, bad = f"{type(e).__name__}: {e}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": bad})
    return err(-32601, f"method not found: {method}")


def serve(role, db_path=None, inp=sys.stdin, out=sys.stdout):
    c = db.init(db_path)
    for line in inp:
        if not line.strip(): continue
        try: msg = json.loads(line)
        except (ValueError, RecursionError):
            r = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(msg, dict): r = handle(c, role, msg)
            else: r = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if r: out.write(json.dumps(r, ensure_ascii=False) + "\n"); out.flush()
    return 0
