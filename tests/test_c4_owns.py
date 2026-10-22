from strata import c4_layered as L


def tree(tmp_path):
    for f in ("a/x.py", "a/y.js", "b/z.py", "b/n.txt", "node_modules/q.js", ".hid/h.py", "top.sql"):
        p = tmp_path / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("")
    return tmp_path


def run(tmp_path, owns):
    objs = [{"id": i, "kind": "component", "name": i, "owns": o} for i, o in owns.items()]
    m = {"project": {"root": "."}, "objects": objs, "links": [], "contracts": [], "behavior": {}, "flows": []}
    return [f for f in L.check(m, tree(tmp_path))[1] if f["id"].startswith("C4-OWNS")]


def test_empty(tmp_path):
    r = run(tmp_path, {"p": ["a", "nope/*.py"], "q": ["b/*.py"]})
    assert [(f["id"], f["subject"]) for f in r] == [("C4-OWNS-EMPTY", "p")]
    assert run(tmp_path, {"p": ["a"], "q": ["b/*.py"]}) == []


def test_overlap(tmp_path):
    r = run(tmp_path, {"p": ["a"], "q": ["a/*.py", "b"]})
    assert [(f["id"], f["subject"]) for f in r] == [("C4-OWNS-OVERLAP", "a/x.py")]
    assert "p" in r[0]["message"] and "q" in r[0]["message"]
    assert run(tmp_path, {"p": ["a/*.js"], "q": ["a/*.py"]}) == []


def test_coverage(tmp_path):
    root = tree(tmp_path)
    assert L.coverage({"p": ["a"]}, root) == {".": ["top.sql"], "b": ["z.py"]}
    assert L.coverage({"p": ["a", "b", "top.sql"]}, root) == {}
