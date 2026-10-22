import yaml
from strata import c4_layered as L, db
from conftest import run
from test_c4_layered import folder  # noqa: F401  (fixture)


def _tech(folder, **tech):
    mp = folder / "map.yaml"; m = yaml.safe_load(mp.read_text())
    for o in m["objects"]:
        if o["id"] in tech: o["tech"] = tech[o["id"]]
    mp.write_text(yaml.safe_dump(m, sort_keys=False))
    return m


def test_tech_roundtrip_context_and_diff(folder, tmp_path):
    m = _tech(folder, **{m_["id"]: "Python 3.12" for m_ in yaml.safe_load((folder / "map.yaml").read_text())["objects"][:1]})
    oid = m["objects"][0]["id"]
    dbp = tmp_path / "t.db"
    assert run(dbp, "c4", "import", str(folder), "--project", "p")[0] == 0
    c = db.connect(dbp)
    assert c.execute("SELECT technology FROM c4_object WHERE id=?", (oid,)).fetchone()[0] == "Python 3.12"
    out = tmp_path / "out"
    assert run(dbp, "c4", "export", str(out), "--project", "p")[0] == 0
    assert L.load(out)[0]["objects"][0]["tech"] == "Python 3.12"
    kind = m["objects"][0]["kind"]
    assert f"[{kind}: Python 3.12]" in L.context_text(c, "p", oid)
    assert f"[{kind}: " not in L.context_text(c, "p", m["objects"][1]["id"])
    _tech(folder, **{oid: "Rust"})
    assert oid in L.diff_model(c, L.load(folder)[0], "p")["object"]["changed"]


def test_bad_tech_is_error(folder):
    _tech(folder, **{yaml.safe_load((folder / "map.yaml").read_text())["objects"][0]["id"]: 3})
    m, errs = L.load(folder)
    assert "C4-BAD-TECH" in {f["id"] for f in L.check(m, folder)[0] + errs}


def test_tech_missing_rule():
    mk = lambda **kw: {"project": {"root": "."}, "objects": [{"id": "a", "kind": "app", "name": "a", **kw}, {"id": "s", "kind": "store", "name": "s", "tech": "SQLite"},
                       {"id": "c", "kind": "component", "name": "c"}], "links": [], "contracts": [], "behavior": {}, "flows": []}
    subj = lambda m: {f["subject"] for f in L.check(m, ".")[1] if f["id"] == "C4-TECH-MISSING"}
    assert subj(mk()) == {"a"}          # app without tech warns; store with tech and component do not
    assert subj(mk(tech="Python")) == set()
