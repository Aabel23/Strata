import pathlib, shutil
from strata import c4_layered as L

FIX = pathlib.Path(__file__).parent / "fixtures/c4_layered"
REPO = pathlib.Path(__file__).parent.parent / "docs/c4"


def _roundtrip(src, tmp_path):
    m, _ = L.load(src)
    d2 = tmp_path / "out"; d2.mkdir()
    assert L.write_model(m, d2)
    assert L.load(d2)[0] == m
    assert L.write_model(m, d2) == []
    return m, d2


def test_roundtrip_fixture(tmp_path): _roundtrip(FIX, tmp_path)


def test_roundtrip_repo_c4(tmp_path):
    src = tmp_path / "src"; shutil.copytree(REPO, src)
    _roundtrip(src, tmp_path)


def test_removal_touches_only_removed_file(tmp_path):
    m, d = _roundtrip(FIX, tmp_path)
    (d / "notes.txt").write_text("x"); (d / "other").mkdir(); (d / "other/a.yaml").write_text("x")
    m["flows"] = m["flows"][1:]
    assert L.write_model(m, d) == [f"flows/{L.load(FIX)[0]['flows'][0]['id']}.yaml"]
    assert (d / "notes.txt").exists() and (d / "other/a.yaml").exists() and (d / "map.yaml").exists()
    m["contracts"] = []; m["behavior"] = {}
    assert all(c.split("/")[0] in ("contracts", "behavior") for c in L.write_model(m, d))
    assert L.load(d)[0] == m
