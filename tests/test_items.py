import importlib.util, io, json, pathlib, re, sqlite3, threading
import pytest
from strata import db, service

ROOT = pathlib.Path(__file__).parent.parent
sp = importlib.util.spec_from_file_location("cli", ROOT / "strata.py"); cli = importlib.util.module_from_spec(sp); sp.loader.exec_module(cli)
GOOD = {"goal": "g", "acceptance": ["a"], "verify": "v", "scope": {"touch": ["x"]}, "open_questions": []}


@pytest.fixture
def c(tmp_path):
    c = db.init(str(tmp_path / "t.db")); db.add_project(c, "p", "P"); return c


def task(c, status="approved", spec=GOOD, **kw):
    return service.add_item(c, "main", "p", "task", "T", status=status, spec=spec, **kw)


def st(c, i): return tuple(c.execute("SELECT status,owner FROM item WHERE id=?", (i,)).fetchone())
def denied(c): return [r[0] for r in c.execute("SELECT json_extract(after,'$.to') FROM audit WHERE tool='denied:item.transition' ORDER BY id")]


def test_schema_columns_and_checks(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(item)")}
    assert {"claimed_at", "spec"} <= cols and "scope" not in cols
    for kind in ("step", "gate"): service.add_item(c, "main", "p", kind, "k")
    task(c, status="review")
    with pytest.raises(sqlite3.IntegrityError): c.execute("UPDATE item SET spec='{bad' WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError): c.execute("INSERT INTO item_dep VALUES(1,1)")


def test_dep_cycle_detected(c):
    a, b, d = task(c), task(c), task(c)
    assert service.dep(c, "main", a, b) and not service.dep(c, "main", a, b)  # dup is a no-op
    service.dep(c, "main", b, d)
    for x, y in ((d, a), (b, a), (a, a)):
        with pytest.raises(ValueError): service.dep(c, "main", x, y)
    assert c.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 2
    assert service.dep(c, "main", a, b, add=False) and c.execute("SELECT count(*) FROM item_dep").fetchone()[0] == 1


def test_happy_path_and_table(c):
    t = task(c)
    service.transition(c, "coder", t, "doing", "c1")
    row = c.execute("SELECT owner,claimed_at FROM item WHERE id=?", (t,)).fetchone()
    assert row["owner"] == "c1" and row["claimed_at"]
    with pytest.raises(PermissionError, match="only the owner"): service.transition(c, "coder", t, "review", "c2", "ev")
    with pytest.raises(PermissionError, match="needs a note"): service.transition(c, "coder", t, "review", "c1")
    service.transition(c, "coder", t, "review", "c1", "pytest 5 pass")
    with pytest.raises(PermissionError, match="owner may not approve"): service.transition(c, "main", t, "done", "c1")
    with pytest.raises(PermissionError): service.transition(c, "coder", t, "done", "c9")  # coder never closes
    service.transition(c, "main", t, "done", "main")
    assert st(c, t) == ("done", "c1")
    assert denied(c) == ["review", "review", "done", "done"]


@pytest.mark.parametrize("to", ["proposed", "approved", "open", "doing", "review", "rejected", "done"])
def test_done_is_terminal(c, to):
    t = task(c, status="open")
    service.transition(c, "main", t, "done", note="reason")
    with pytest.raises(PermissionError, match="terminal"): service.transition(c, "main", t, to, note="x")
    assert st(c, t)[0] == "done"


def test_illegal_and_note_rules(c):
    t = task(c, status="proposed")
    with pytest.raises(PermissionError, match="illegal"): service.transition(c, "main", t, "done", note="x")
    with pytest.raises(PermissionError, match="needs a note"): service.transition(c, "main", t, "rejected")
    service.transition(c, "main", t, "rejected", note="no")
    service.transition(c, "main", t, "proposed")  # reopen
    assert st(c, t)[0] == "proposed"
    assert c.execute("SELECT count(*) FROM audit WHERE tool='denied:item.transition'").fetchone()[0] == 2


def test_rework_release_and_stale_submit(c):
    t = task(c)
    service.transition(c, "coder", t, "doing", "c1"); service.transition(c, "coder", t, "review", "c1", "ev")
    with pytest.raises(PermissionError, match="needs a note"): service.transition(c, "main", t, "doing")
    service.transition(c, "main", t, "doing", note="fix X")
    assert st(c, t) == ("doing", "c1")
    assert "fix X" in c.execute("SELECT after FROM audit WHERE tool='item.transition' ORDER BY id DESC").fetchone()[0]
    service.transition(c, "coder", t, "review", "c1", "ev2")
    service.edit_item(c, "main", t, title="changed")  # version moves after submit
    with pytest.raises(PermissionError, match="changed since submit"): service.transition(c, "main", t, "done")
    service.transition(c, "main", t, "doing", note="redo"); service.transition(c, "main", t, "approved")  # release
    assert st(c, t) == ("approved", None)


def test_claim_blocked_by_dep_and_spec(c):
    a, b = task(c), task(c)
    service.dep(c, "main", b, a)
    with pytest.raises(PermissionError, match=f"unfinished dependencies \\[{a}\\]"): service.transition(c, "coder", b, "doing", "c")
    assert [i["id"] for i in service.list_items(c, ready=True)] == [a]
    service.transition(c, "main", a, "doing", "m"); service.transition(c, "main", a, "review", "m", "e"); service.transition(c, "main", a, "done", "other")
    assert [i["id"] for i in service.list_items(c, ready=True)] == [b]
    service.edit_item(c, "main", b, spec={**GOOD, "blocked": True})
    assert service.list_items(c, ready=True) == []
    with pytest.raises(PermissionError, match="blocked"): service.transition(c, "coder", b, "doing", "c")


def test_concurrent_claim_one_wins(tmp_path):
    p = str(tmp_path / "t.db"); c = db.init(p); db.add_project(c, "p", "P"); t = task(c)
    bar, res = threading.Barrier(2), []
    def go(name):
        k = db.connect(p); bar.wait()
        try: service.transition(k, "coder", t, "doing", name); res.append(name)
        except PermissionError: res.append(None)
    th = [threading.Thread(target=go, args=(n,)) for n in ("a", "b")]
    [x.start() for x in th]; [x.join() for x in th]
    assert sorted(r is None for r in res) == [False, True]
    assert st(c, t) == ("doing", next(r for r in res if r))


def test_cas_rowcount_zero(c, monkeypatch):
    t = task(c)
    real = service.db.now
    def race():  # another writer bumps the version between our read and our UPDATE
        c.execute("UPDATE item SET version=version+1 WHERE id=?", (t,)); return real()
    monkeypatch.setattr(service.db, "now", race)
    with pytest.raises(PermissionError, match="concurrently"): service.transition(c, "coder", t, "doing", "x")
    assert st(c, t) == ("approved", None)


def test_approve_gate(c):
    bad = [None, {}, {**GOOD, "goal": ""}, {**GOOD, "acceptance": []}, {**GOOD, "verify": None}, {**GOOD, "scope": {}}, {**GOOD, "open_questions": ["?"]}]
    for spec in bad:
        t = task(c, status="proposed", spec=spec)
        with pytest.raises(PermissionError, match="spec incomplete|open_questions"): service.transition(c, "main", t, "approved")
    service.transition(c, "main", task(c, status="proposed"), "approved")
    i = service.add_item(c, "main", "p", "issue", "k", status="proposed")  # an issue is a task now: the gate applies
    with pytest.raises(PermissionError, match="spec incomplete"): service.transition(c, "main", i, "approved")
    for kind in ("step", "gate"):  # gate applies to task only
        i = service.add_item(c, "main", "p", kind, "k", status="proposed")
        service.transition(c, "main", i, "approved")
        assert st(c, i)[0] == "approved"


@pytest.mark.parametrize("operation", ["add", "edit"])
def test_scope_must_be_object_on_add_and_edit(c, operation):
    bad = {**GOOD, "scope": []}
    if operation == "add":
        with pytest.raises(ValueError, match="spec.scope must be a JSON object"):
            service.add_item(c, "main", "p", "task", "T", status="proposed", spec=bad)
        assert c.execute("SELECT count(*) FROM item").fetchone()[0] == 0
    else:
        t = task(c)
        before = c.execute("SELECT spec,version FROM item WHERE id=?", (t,)).fetchone()
        with pytest.raises(ValueError, match="spec.scope must be a JSON object"):
            service.edit_item(c, "main", t, spec=bad)
        assert tuple(c.execute("SELECT spec,version FROM item WHERE id=?", (t,)).fetchone()) == tuple(before)


def test_approve_legacy_non_object_scope_is_incomplete(c):
    t = task(c, status="proposed")
    legacy = {**GOOD, "scope": []}
    c.execute("UPDATE item SET spec=? WHERE id=?", (json.dumps(legacy), t)); c.commit()
    with pytest.raises(PermissionError, match="spec incomplete: scope.touch"):
        service.transition(c, "main", t, "approved")
    assert st(c, t)[0] == "proposed" and denied(c) == ["approved"]


def test_cli_approve_legacy_non_object_scope_is_clean(tmp_path, capsys):
    db_path = str(tmp_path / "legacy.db")
    c = db.init(db_path); db.add_project(c, "p", "P")
    t = service.add_item(c, "main", "p", "task", "T", status="proposed", spec=GOOD)
    c.execute("UPDATE item SET spec=? WHERE id=?", (json.dumps({**GOOD, "scope": []}), t)); c.commit(); c.close()
    assert cli.main(["item", "approve", str(t), "--db", db_path]) == 1
    out = capsys.readouterr()
    assert "spec incomplete: scope.touch" in out.out and "Traceback" not in out.err


def test_issue_by_coder_reviewer_is_proposed(c):
    for r in ("coder", "reviewer"):
        i = service.add_item(c, r, "p", "issue", "i", status="done")
        assert c.execute("SELECT status FROM item WHERE id=?", (i,)).fetchone()[0] == "proposed"


def test_priority_sort(c):
    for k in ("low", None, "p3", "medium", "p0", "high", "p2", "p1"): task(c, priority=k)
    got = [i["priority"] for i in service.list_items(c, "p")]
    assert got[0] == "p0" and got[-1] is None and got.index("p1") < got.index("p2") < got.index("p3")
    assert got.index("high") < got.index("medium") < got.index("low")
    tie = [i["id"] for i in service.list_items(c, "p") if i["priority"] in ("p1", "high")]
    assert tie == sorted(tie)


def test_cli_flow(tmp_path, capsys, monkeypatch):
    db_ = str(tmp_path / "t.db"); c = db.init(db_); db.add_project(c, "p", "P"); c.close()
    def out(*a):
        rc = cli.main([*a, "--db", db_]); return rc, capsys.readouterr().out
    spec = tmp_path / "s.json"; spec.write_text(json.dumps(GOOD))
    rc, o = out("item", "add", "--project", "p", "--kind", "task", "--title", "one", "--status", "proposed", "--spec", str(spec), "--json"); assert json.loads(o) == {"id": 1}
    out("item", "add", "--project", "p", "--kind", "task", "--title", "two", "--status", "proposed", "--priority", "p0")
    assert out("item", "approve", "2")[0] == 1  # no spec
    assert out("item", "approve", "1")[0] == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(GOOD)))
    assert out("item", "edit", "2", "--spec", "-")[0] == 0 and out("item", "approve", "2")[0] == 0
    assert out("item", "dep", "add", "2", "1")[0] == 0
    assert [i["id"] for i in json.loads(out("item", "ready", "--json")[1])] == [1]
    assert [i["id"] for i in json.loads(out("item", "list", "--status", "approved", "--json")[1])] == [2, 1]  # p0 first
    assert out("item", "claim", "2", "--as", "w")[0] == 1  # blocked
    assert out("item", "claim", "1", "--as", "w")[0] == 0
    assert out("item", "submit", "1", "--note", "ev", "--as", "x")[0] == 1  # not owner
    assert out("item", "submit", "1", "--note", "ev", "--as", "w")[0] == 0
    assert json.loads(out("item", "list", "--owner", "w", "--json")[1])[0]["status"] == "review"
    assert out("item", "approve", "1", "--as", "w")[0] == 1  # self-approve
    assert out("item", "approve", "1")[0] == 0
    s = json.loads(out("item", "show", "2", "--json")[1])
    assert s["depends_on"][0]["status"] == "done" and s["spec"]["goal"] == "g"
    assert "depends on #1" in out("item", "show", "2")[1]
    with pytest.raises(SystemExit): out("item", "reject", "2")  # --note required
    assert out("item", "reject", "2", "--note", "no")[0] == 0 and out("item", "dep", "rm", "2", "1")[0] == 0
    assert out("item", "release", "2")[0] == 1  # rejected -> approved is illegal


OLD_ITEM = """CREATE TABLE item(id INTEGER PRIMARY KEY, project TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('rule','task','issue','knowledge','draft','note')), title TEXT NOT NULL, body TEXT,
      status TEXT NOT NULL CHECK(status IN ('proposed','approved','open','doing','done','rejected')),
      priority TEXT, scope TEXT, always_load INT NOT NULL DEFAULT 0, core INT NOT NULL DEFAULT 0,
      owner TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, version INT NOT NULL DEFAULT 1);
      INSERT INTO item(id,project,kind,title,body,status,scope) VALUES(7,'p','task','alpha','zebrax','open','{"touch":["a"]}'),(9,'p','task','beta','x','done','src/**');"""


def old_db(p):
    k = sqlite3.connect(p); k.executescript(OLD_ITEM); k.commit(); k.close()


def test_migration_old_db_with_scope(tmp_path):
    p = str(tmp_path / "old.db"); old_db(p)
    for _ in range(2):
        c = db.init(p)
        assert [r[0] for r in c.execute("SELECT id FROM item ORDER BY id")] == [7, 9]
        assert json.loads(c.execute("SELECT spec FROM item WHERE id=7").fetchone()[0]) == {"scope": {"touch": ["a"]}}
        assert json.loads(c.execute("SELECT spec FROM item WHERE id=9").fetchone()[0]) == {"scope": "src/**"}
        assert [h["ref"] for h in service.search(c, "zebrax", src="item")] == [7]
        assert c.execute("SELECT count(*) FROM search WHERE src='item'").fetchone()[0] == 2
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone()


def test_migration_backup_and_rollback(tmp_path, monkeypatch):
    p = tmp_path / "old.db"; old_db(str(p)); pre = p.read_bytes()
    def boom(c): raise RuntimeError("boom")
    monkeypatch.setattr(db, "_finish_item", boom)
    with pytest.raises(RuntimeError): db.init(str(p))
    k = sqlite3.connect(p)
    assert [r[0] for r in k.execute("SELECT id FROM item ORDER BY id")] == [7, 9] and "scope" in [r[1] for r in k.execute("PRAGMA table_info(item)")]
    assert not k.execute("SELECT 1 FROM sqlite_master WHERE name='item_old'").fetchone(); k.close()
    bk = list((tmp_path / "backups").glob("strata-*.db"))
    assert len(bk) == 1 and bk[0].read_bytes() == pre
    monkeypatch.undo(); db.init(str(p)).close()


def test_cli_rework_close_approve_guard(tmp_path, capsys):
    db_ = str(tmp_path / "t.db"); c = db.init(db_); db.add_project(c, "p", "P")
    a = task(c); b = service.add_item(c, "main", "p", "issue", "I", status="open"); c.close()
    def out(*x): return cli.main([*x, "--db", db_])
    assert out("item", "approve", str(a)) == 1  # approved is not approvable
    assert out("item", "claim", str(a), "--as", "w") == 0
    assert out("item", "approve", str(a)) == 1 and "approve only from" in capsys.readouterr().out
    k = db.connect(db_); assert st(k, a) == ("doing", "w")
    assert out("item", "submit", str(a), "--note", "ev", "--as", "w") == 0
    with pytest.raises(SystemExit): out("item", "rework", str(a))
    assert out("item", "rework", str(b), "--note", "x") == 1 and "rework only from review" in capsys.readouterr().out
    assert out("item", "rework", str(a), "--note", "fix") == 0 and st(k, a)[0] == "doing"
    with pytest.raises(SystemExit): out("item", "close", str(b))
    assert out("item", "close", str(b), "--note", "ok") == 0 and st(k, b)[0] == "done"


REAL = pathlib.Path("/home/abel/project/tools/strata/strata.db")


@pytest.mark.skipif(not REAL.exists(), reason="no real strata.db")
def test_migration_on_copy_of_real_db(tmp_path):
    src = sqlite3.connect(f"file:{REAL}?mode=ro", uri=True); p = str(tmp_path / "copy.db"); dst = sqlite3.connect(p)
    src.backup(dst); src.close(); dst.close()
    pre = sqlite3.connect(p); pre.row_factory = sqlite3.Row
    ids = [r[0] for r in pre.execute("SELECT id FROM item ORDER BY id")]
    word = next(w for r in pre.execute("SELECT title FROM item") for w in re.findall(r"[A-Za-z]{5,}", r[0]))
    hits = lambda k: sorted(h["ref"] for h in service.search(k, word, src="item", limit=100))
    before = hits(pre); pre.close()
    c = db.init(p)
    assert [r[0] for r in c.execute("SELECT id FROM item ORDER BY id")] == ids and before
    assert hits(c) == before
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "scope" not in [r["name"] for r in c.execute("PRAGMA table_info(item)")]
    snap = lambda k: (tuple(k.execute("SELECT count(*), sum(version), max(updated_at) FROM item").fetchone()), k.execute("SELECT count(*) FROM audit").fetchone()[0])
    first = snap(c); c.close(); c = db.init(p)
    assert snap(c) == first and hits(c) == before
