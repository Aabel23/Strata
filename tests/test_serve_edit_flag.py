import pytest
import importlib.util
from conftest import ROOT
from strata import server

# strata/ package shadows strata.py, so load the CLI by path
spec = importlib.util.spec_from_file_location("strata_cli", ROOT / "strata.py")
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)


@pytest.mark.parametrize("flags,want", [([], None), (["--allow-edit"], True), (["--no-edit"], False)])
def test_serve_edit_flag(monkeypatch, flags, want):
    seen = {}
    def fake(*a, **kw): seen.update(kw); raise SystemExit(0)
    monkeypatch.setattr(server, "make_server", fake)
    with pytest.raises(SystemExit): cli.main(["serve", *flags])
    assert seen["allow_edit"] is want
