import pytest
from strata import c4_layered as L

O = lambda id, kind, parent=None, **kw: {"id": id, "kind": kind, "name": id, **({"parent": parent} if parent else {}), **kw}
K = lambda id, a, b, name="x", **kw: {"id": id, "from": a, "to": b, "name": name, **kw}
BASE = [O("sys", "system"), O("a1", "app", "sys"), O("a2", "app", "sys"), O("c1", "component", "a1"), O("c2", "component", "a1"),
        O("d1", "component", "a2"), O("db", "store", "sys"), O("u", "actor")]


def ids(objects, links=(), contracts=(), behavior=None):
    m = {"project": {"root": "."}, "objects": objects, "links": list(links), "contracts": list(contracts), "behavior": behavior or {}, "flows": []}
    return {f["id"] for f in L.check(m, ".")[1]}


def mk(*extra, drop=()):
    return [o for o in BASE if o["id"] not in drop] + list(extra)


# (rule, bad, good): each is (objects, links, contracts, behavior)
CON = {"id": "k.t", "transport": "HTTP", "start": "a.py::A", "end": "a.py::A"}
CASES = [
    ("C4-PERSON-TARGET", (BASE, [K("l", "u", "c1")]), (BASE, [K("l", "u", "a1")])),
    ("C4-COMP-PARENT", (mk(O("c3", "component", "sys")), []), (BASE, [])),
    ("C4-COMP-CROSS", (BASE, [K("l", "c1", "d1")]), (BASE, [K("l", "c1", "c2")])),
    ("C4-PARENT-LEVEL", (mk(O("x", "component", "db")), []), (BASE, [])),
    ("C4-SELF-LINK", (BASE, [K("l", "c1", "c1")]), (BASE, [K("l", "c1", "c2")])),
    ("C4-LINK-NOLABEL", (BASE, [K("l", "c1", "c2", name=None)]), (BASE, [K("l", "c1", "c2")])),
    ("C4-LINK-NOPROTO", (BASE, [K("l", "a1", "a2")]), (BASE, [K("l", "a1", "a2", "HTTP call")])),
    ("C4-LINK-DIR", (BASE, [K("l", "c1", "c2"), K("m", "c2", "c1", "y")]), (BASE, [K("l", "c1", "c2")])),
    ("C4-LINK-DUP", (BASE, [K("l", "c1", "c2"), K("m", "c1", "c2")]), (BASE, [K("l", "c1", "c2"), K("m", "c1", "c2", "y")])),
    ("C4-FILE-OBJECT", (mk(O("f", "component", "a1", owns=["src/f.py"])), []), (mk(O("f", "component", "a1", owns=["src/**"])), [])),
    ("C4-STORE-SHARED", (BASE, [K("l", "a1", "db", "sql"), K("m", "a2", "db", "sql")]), (BASE, [K("l", "a1", "db", "sql")])),
    ("C4-ORPHAN", (BASE, []), (BASE, [K("l", "u", "a1"), K("m", "c1", "c2"), K("n", "a1", "d1"), K("o", "a1", "db"), K("p", "a2", "d1")])),
    ("C4-CYCLE-APP", (BASE, [K("l", "c1", "d1"), K("m", "d1", "c1", "y")]), (BASE, [K("l", "c1", "d1")])),
    ("C4-CONTRACT-ORPHAN", (BASE, [K("l", "c1", "c2")], [CON]), (BASE, [K("l", "c1", "c2", detail="k.t")], [CON])),
    ("C4-VIEW-SIZE", ([O("p", "system")] + [O(f"a{i}", "app", "p") for i in range(13)], []), ([O("p", "system")] + [O(f"a{i}", "app", "p") for i in range(12)], [])),
    ("C4-BEHAVIOR-UNREACHABLE", (BASE, [], [], {"c1": {"initial": "s", "states": {"s": {}, "t": {}}, "transitions": []}}),
     (BASE, [], [], {"c1": {"initial": "s", "states": {"s": {}, "t": {}}, "transitions": [{"from": "s", "to": "t"}]}})),
]


@pytest.mark.parametrize("rule,bad,good", CASES, ids=[c[0] for c in CASES])
def test_rule(rule, bad, good):
    assert rule in ids(*bad)
    assert rule not in ids(*good)


def test_behavior_without_initial_is_skipped():
    assert "C4-BEHAVIOR-UNREACHABLE" not in ids(BASE, [], [], {"c1": {"states": {"s": {}}, "transitions": []}})


def test_noproto_accepts_contract_transport():
    c = {**CON, "id": "k.t"}
    assert "C4-LINK-NOPROTO" not in ids(BASE, [K("l", "a1", "a2", detail="k.t")], [c])
