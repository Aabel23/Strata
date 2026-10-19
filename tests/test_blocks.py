import json, os, pathlib, subprocess, sys
import pytest
from strata import blocks, c4, db

ROOT = pathlib.Path(__file__).resolve().parent.parent

GOOD = [
    {"type": "md", "text": "x"},
    {"type": "layers", "rows": [{"title": "T", "cells": [{"name": "n", "note": "m", "status": "done"}, {"name": "o", "status": "plan"}]}]},
    {"type": "mermaid", "code": "flowchart LR\n A-->B"},
    {"type": "table", "head": ["a"], "rows": [["1"], ["2"]]},
    {"type": "legend", "items": [{"label": "l", "status": "done"}]},
    {"type": "question", "q": "?", "options": [{"label": "A"}, {"label": "B", "note": "n"}], "recommend": "B"},
    {"type": "c4", "ids": ["a"]},
    {"type": "query", "src": "item", "where": {"status": "open"}, "limit": 5},
]


def test_good_blocks_pass():
    assert blocks.validate(GOOD) == ([], [])


def bad(i, **kw):
    b = dict(GOOD[i]); b.update(kw); return b

def without(i, k):
    b = dict(GOOD[i]); del b[k]; return b


@pytest.mark.parametrize("block,msg", [
    ({"type": "nope"}, "block[0]: unknown type 'nope'"),
    ("str", "block[0]: unknown type 'str'"),
    (without(0, "text"), "block[0] type md: missing 'text'"),
    (without(1, "rows"), "block[0] type layers: missing 'rows'"),
    (bad(1, rows=[{"title": "T", "cells": [{"name": "n", "status": "x"}]}]), "status must be done|plan"),
    (bad(1, rows=[{"cells": []}]), "rows[0]: missing 'title'"),
    (without(2, "code"), "type mermaid: missing 'code'"),
    (without(3, "head"), "type table: missing 'head'"),
    (bad(3, rows=["x"]), "rows[0]: must be a list"),
    (without(4, "items"), "type legend: missing 'items'"),
    (bad(4, items=[{"label": "l", "status": "?"}]), "items[0]: status"),
    (without(5, "q"), "type question: missing 'q'"),
    (bad(5, options=[]), "type question: missing 'options'"),
    (bad(5, recommend="Z"), "recommend 'Z' matches no option label"),
    (without(6, "ids"), "type c4: missing 'ids'"),
    (bad(6, ids=[]), "type c4: missing 'ids'"),
    (bad(7, src="audit"), "src must be item|decision"),
    (bad(7, where={"body": "x"}), "where column 'body' not allowed for item"),
    (bad(7, where={"scope": "x"}), "where column 'scope' not allowed for item"),
    (bad(7, where={"status": ["a"]}), "non-empty string or an integer"),
    (bad(7, where={"status": ""}), "non-empty string or an integer"),
    (bad(7, where={"core": True}), "non-empty string or an integer"),
    (bad(7, limit=0), "limit must be an integer 1..200"),
])
def test_bad_block(block, msg):
    errs, _ = blocks.validate([block])
    assert any(msg in e for e in errs), errs


def test_error_index_in_message():
    errs, _ = blocks.validate([GOOD[0], GOOD[0], GOOD[0], {"type": "layers"}])
    assert errs == ["block[3] type layers: missing 'rows'"]


def test_not_a_list():
    assert blocks.validate({"type": "md"})[0] == ["blocks must be a list"]


def test_c4_missing_ids_warn_only(tmp_path):
    c = db.init(tmp_path / "t.db")
    c4.import_yaml(c, ROOT / "examples/project1_app.strata.yaml", "p")
    errs, warns = blocks.validate([{"type": "c4", "ids": ["server", "ghost"]}], c, "p")
    assert errs == [] and len(warns) == 1 and "ghost" in warns[0]


def cli(dbp, *args):
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), *args], capture_output=True, text=True,
                       env={**os.environ, "STRATA_DB": str(dbp)})
    return r.returncode, r.stdout


def test_cli_page_put_validate_list(tmp_path):
    dbp = tmp_path / "t.db"
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"project": "p", "slug": "s", "title": "T", "kind": "note", "blocks": GOOD}))
    assert cli(dbp, "page", "validate", str(f))[0] == 0
    assert not dbp.exists()  # validate must not write
    assert cli(dbp, "page", "put", str(f))[0] == 0
    code, out = cli(dbp, "page", "list", "--project", "p")
    assert code == 0 and "p/s" in out and "T" in out
    assert "p/s" not in cli(dbp, "page", "list", "--project", "other")[1]
    f.write_text(json.dumps({"project": "p", "slug": "bad slug", "title": "T", "kind": "x", "blocks": [{"type": "layers"}]}))
    code, out = cli(dbp, "page", "validate", str(f))
    assert code == 1 and "block[0] type layers: missing 'rows'" in out and "kind" in out and "slug" in out
    assert cli(dbp, "page", "put", str(f))[0] == 1
    assert len(db.list_pages(db.connect(dbp))) == 1


def test_example_page_validates():
    doc = json.loads((ROOT / "examples/strata-design.page.json").read_text())
    assert blocks.validate_doc(doc) == ([], [])


# ---- task #41: doc YAML needs blocks; doc validate ----
import pytest, subprocess, sys, pathlib as _pl


@pytest.mark.parametrize("tail", ["", "blocks:\n", "blocks: {}\n", "blocks: text\n"])
def test_load_doc_requires_blocks(tail):
    assert any("blocks" in e for e in blocks.load_doc("title: T\n" + tail)[1])


def _validate(tmp_path, content=None):
    f = tmp_path / "d.yaml"
    f.unlink(missing_ok=True)
    if content is not None: f.write_text(content)
    r = subprocess.run([sys.executable, str(_pl.Path(__file__).resolve().parent.parent / "strata.py"), "doc", "validate", str(f)],
                       capture_output=True, text=True)
    return r.returncode, r.stderr


def test_doc_validate_cli(tmp_path):
    assert _validate(tmp_path, "title: T\nblocks:\n  - {md: hi}\n")[0] == 0
    for bad in (None, "a: [", "- 1\n", "title: T\nblocks: x\n", "title: T\nblocks:\n  - {type: nope}\n"):
        code, err = _validate(tmp_path, bad)
        assert code == 1 and "ERROR" in err
