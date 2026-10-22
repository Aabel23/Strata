import copy, importlib.util, json, pathlib, sqlite3, threading, urllib.request
import pytest
from strata import db, roadmap, server, service

ROOT = pathlib.Path(__file__).parent.parent
sp = importlib.util.spec_from_file_location("cli", ROOT / "strata.py"); cli = importlib.util.module_from_spec(sp); sp.loader.exec_module(cli)
SRC = pathlib.Path("/home/abel/project/internproj/project1_app/documentation/plan")
PLAN, PROG = SRC / "plan.json", SRC / "progress" / "roadmap-progress.json"
REAL_GATES = "G0=0;G1=1,2;G2=3,4;G3=5,6;G4=7"
real = pytest.mark.skipif(not (PLAN.is_file() and PROG.is_file()), reason="project1_app plan not available")


def run(capsys, *argv):
    rc = cli.main([str(x) for x in argv]); out = capsys.readouterr()
    return rc, out.out + out.err


@pytest.fixture
def dbp(tmp_path):
    p = tmp_path / "t.db"; c = db.init(str(p)); db.add_project(c, "p", "P"); c.close(); return str(p)


def rm(capsys, dbp, *a): return run(capsys, "roadmap", *a, "--project", "p", "--roadmap", "r", "--db", dbp)


def mini(tmp_path, proof="old proof", body="<b>bold</b> <code>x</code> <a href=\"u.md\">l</a><br>next <i>it</i>", steps=("0.1", "0.2", "1.1")):
    """Smallest plan with the shape of plan.json: phase 0 under G0, phase 1 under G1."""
    ph = lambda n: {"anchor": f"p{n}", "title": f"Phase {n}", "intro": "i", "mark": "m", "gate": {"label": "g", "body": "b"},
                    "steps": [{"id": k, "title": f"T{k}", "body": body, "proof": proof} for k in steps if k.startswith(f"{n}.")]}
    plan = {"version": 1, "banner": "b", "header": {"eyebrow": "e", "title": "Mini", "lead": "l", "meta": []}, "summary": [], "progress": {"title": "t", "intro": "i", "guide": "g"},
            "sections": [{"id": "ban-do", "title": "2", "route": [{"href": "#p0", "code": "G0", "title": "Gate zero", "detail": "d"}, {"href": "#p1", "code": "G1", "title": "Gate one", "detail": "d"}]},
                         {"id": "chi-tiet", "title": "3", "phases": [ph(0), ph(1)]}], "gates": {"G0": [0], "G1": [1]}}
    f = tmp_path / "plan.json"; f.write_text(json.dumps(plan)); return f, plan


def put(f, plan): f.write_text(json.dumps(plan))


def prog(tmp_path, **steps):
    f = tmp_path / "prog.json"
    f.write_text(json.dumps({"version": 1, "steps": {k: {"status": s, "owner": "o", "updated": "2026-10-13", "evidence": "e", "reviewer": "u" if s == "done" else "", "note": ""} for k, s in steps.items()}, "gates": {}}))
    return f


def item(c, key, kind="step"):
    r = roadmap._find(c, "p", "r", kind, key); return r and {**dict(r), "spec": json.loads(r["spec"])}


def test_html_to_md():
    assert roadmap.html_to_md('<b>a</b> <strong>b</strong> <code>c</code> <a href="x y.md">t</a><br/>n <i>z</i><p>q</p>') == "**a** **b** `c` [t](x%20y.md)\nn zq"
    assert roadmap.html_to_md("<a>no href</a> &amp; &lt;") == "no href & <"


def test_page_kind_migration_keeps_rows(tmp_path):
    p = str(tmp_path / "old.db"); c = sqlite3.connect(p)
    c.executescript(db.SCHEMA.read_text().replace("'note','plan'", "'note'"))
    c.execute("INSERT INTO page(project,slug,title,kind,blocks,text) VALUES('p','a','Alpha','note','[]','findme')"); c.commit(); c.close()
    c = db.init(p); c = db.init(p)  # second run is a no-op
    assert c.execute("SELECT slug,kind FROM page").fetchall()[0][:] == ("a", "note")
    db.put_page(c, "p", "roadmap-x", "R", "plan", {"v": 1})
    assert len(c.execute("SELECT 1 FROM search WHERE src='page'").fetchall()) == 2 and list((tmp_path / "backups").glob("strata-*.db"))
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='page_old'").fetchone()


def test_import_upsert_orphan_stale_gate(tmp_path, dbp, capsys):
    f, plan = mini(tmp_path); pr = prog(tmp_path, **{"0.1": "done", "0.2": "done"})
    assert rm(capsys, dbp, "import", f, "--progress", pr)[0] == 0
    c = db.connect(dbp)
    s = item(c, "0.1")
    assert s["status"] == "done" and s["owner"] == "o" and s["spec"]["reviewer"] == "u" and s["spec"]["acceptance"] == ["old proof"]
    assert s["body"] == "**bold** `x` [l](u.md)\nnext it"  # html -> markdown
    assert item(c, "G0", "gate")["status"] == "approved" and len(c.execute("SELECT 1 FROM item_dep WHERE item_id=?", (item(c, "G0", "gate")["id"],)).fetchall()) == 2
    # idempotent: no version bump, no new audit rows
    v = [r[0] for r in c.execute("SELECT version FROM item ORDER BY id")]; n = c.execute("SELECT count(*) FROM audit").fetchone()[0]
    out = rm(capsys, dbp, "import", f, "--progress", pr)[1]
    assert "0 new, 0 updated, 3 unchanged" in out
    assert [r[0] for r in c.execute("SELECT version FROM item ORDER BY id")] == v
    assert c.execute("SELECT count(*) FROM audit").fetchone()[0] == n + 1  # only page.put
    # a step missing from the new plan is kept and marked orphan; done steps are never deleted
    plan2 = copy.deepcopy(plan); plan2["sections"][1]["phases"][0]["steps"].pop()  # drop 0.2 (done)
    put(f, plan2); rm(capsys, dbp, "import", f)
    assert item(c, "0.2")["spec"]["orphan"] and item(c, "0.2")["status"] == "done"
    rc, out = rm(capsys, dbp, "gate", "pass", "G0", "--as", "user")
    assert rc == 1 and "orphan" in out and item(c, "G0", "gate")["status"] == "approved"
    put(f, plan); rm(capsys, dbp, "import", f)  # back in the plan: orphan cleared
    assert "orphan" not in item(c, "0.2")["spec"]
    # acceptance of a done step changes -> stale, gate refused until re-accepted
    plan3 = copy.deepcopy(plan); plan3["sections"][1]["phases"][0]["steps"][0]["proof"] = "new proof"
    put(f, plan3); rm(capsys, dbp, "import", f)
    assert item(c, "0.1")["spec"]["stale"] and item(c, "0.1")["status"] == "done" and item(c, "0.1")["spec"]["acceptance"] == ["new proof"]
    assert json.loads(rm(capsys, dbp, "check", "--json")[1])["stale"] == ["0.1"]
    rc, out = rm(capsys, dbp, "gate", "pass", "G0", "--as", "user")
    assert rc == 1 and "stale" in out and "0.1" in out
    assert rm(capsys, dbp, "reaccept", "0.1")[0] == 1 and item(c, "0.1")["spec"]["stale"]  # needs --as user
    assert rm(capsys, dbp, "reaccept", "0.1", "--as", "user")[0] == 0
    assert rm(capsys, dbp, "gate", "pass", "G0", "--as", "user", "--evidence", "doc.md")[0] == 0
    g = item(c, "G0", "gate")
    assert g["status"] == "done" and g["spec"]["evidence"] == "doc.md" and g["spec"]["reviewer"] == "user"
    assert c.execute("SELECT actor_role,after FROM audit WHERE tool='roadmap.gate_pass'").fetchone()[1].count("user")


def test_gate_pass_needs_user_and_done_steps(tmp_path, dbp, capsys):
    f, _ = mini(tmp_path); rm(capsys, dbp, "import", f, "--progress", prog(tmp_path, **{"0.1": "done"}))
    c = db.connect(dbp)
    for extra in ([], ["--as", "main"], ["--as", "coder"]):
        rc, out = rm(capsys, dbp, "gate", "pass", "G0", *extra)
        assert rc == 1 and "--as user" in out
    assert item(c, "G0", "gate")["status"] == "approved"
    rc, out = rm(capsys, dbp, "gate", "pass", "G0", "--as", "user")  # 0.2 still todo
    assert rc == 1 and "0.2" in out and item(c, "G0", "gate")["status"] == "approved"
    assert c.execute("SELECT count(*) FROM audit WHERE tool='denied:roadmap.gate_pass'").fetchone()[0] == 4


def test_step_lifecycle_with_item_verbs(tmp_path, dbp, capsys):
    f, _ = mini(tmp_path); rm(capsys, dbp, "import", f)
    c = db.connect(dbp); i = item(c, "0.1")["id"]
    assert item(c, "0.1")["status"] == "approved" and i in [x["id"] for x in service.list_items(c, "p", ready=True)]
    for argv in (["claim", i, "--as", "ann"], ["submit", i, "--note", "evidence.md", "--as", "ann"], ["approve", i, "--as", "bob"]):
        assert run(capsys, "item", *argv, "--db", dbp)[0] == 0
    s = item(c, "0.1"); assert (s["status"], s["owner"]) == ("done", "ann")
    # blocked in progress -> approved + spec.blocked, never ready
    pr = prog(tmp_path); data = json.loads(pr.read_text()); data["steps"] = {"0.2": {"status": "blocked", "owner": "o", "note": "waiting for HW"}}; pr.write_text(json.dumps(data))
    rm(capsys, dbp, "import", f, "--progress", pr)
    s = item(c, "0.2"); assert s["status"] == "approved" and s["spec"]["blocked"] == "waiting for HW" and s["spec"]["note"] == "waiting for HW"
    assert s["id"] not in [x["id"] for x in service.list_items(c, "p", ready=True)]


def test_uniqueness_index(tmp_path, dbp, capsys):
    f, _ = mini(tmp_path); rm(capsys, dbp, "import", f); c = db.connect(dbp)
    with pytest.raises(sqlite3.IntegrityError):
        service.add_item(c, "main", "p", "step", "dup", spec={"roadmap": "r", "step_key": "0.1"})


@real
def test_real_plan_matches_progress(tmp_path, dbp, capsys):
    plan, pj = json.loads(PLAN.read_text()), json.loads(PROG.read_text())
    keys = [s["id"] for ph in next(s for s in plan["sections"] if s["id"] == "chi-tiet")["phases"] for s in ph["steps"]]
    assert rm(capsys, dbp, "import", PLAN, "--progress", PROG, "--gates", REAL_GATES)[0] == 0
    c = db.connect(dbp)
    items = {json.loads(r["spec"])["step_key"]: r for r in c.execute("SELECT * FROM item WHERE kind='step'")}
    assert sorted(items) == sorted(keys) and set(pj["steps"]) <= set(keys)
    want = {"todo": "approved", "doing": "doing", "review": "review", "done": "done", "blocked": "approved"}
    for k in keys:
        r, sp, pr = items[k], json.loads(items[k]["spec"]), pj["steps"].get(k)
        assert r["status"] == (want[pr["status"]] if pr else "approved"), k
        assert r["owner"] == ((pr["owner"] or None) if pr else None), k
        for f in ("reviewer", "evidence", "note", "updated"): assert sp[f] == (pr[f] if pr else ""), (k, f)
        assert sp["title"] == r["title"] and sp["phase"] == int(k.split(".")[0]) and "<" not in (r["body"] or "") and sp["acceptance"] == [sp["proof"]]
    # a source link became markdown
    assert "](" in items["0.1"]["body"] and "<a" not in items["0.1"]["body"]
    # gates: G0 approved in progress.json
    assert {g: item(c, g, "gate")["status"] for g in ("G0", "G1", "G2", "G3", "G4")} == {"G0": "done", "G1": "approved", "G2": "approved", "G3": "approved", "G4": "approved"}
    pg = db.get_page(c, "p", "roadmap-r")
    assert pg["kind"] == "plan" and pg["blocks"]["gates"][1] == {"id": "G1", "phases": [1, 2]} and [s["id"] for s in pg["blocks"]["sections"]] == ["hien-trang", "ban-do", "chi-tiet", "song-song", "can-ban", "nguon"]
    assert all(isinstance(s, str) for ph in pg["blocks"]["sections"][2]["phases"] for s in ph["steps"]) and "<" not in pg["blocks"]["sections"][0]["facts"][0]["body"]
    # re-import: nothing changes
    n, v = c.execute("SELECT count(*) FROM audit").fetchone()[0], c.execute("SELECT sum(version) FROM item").fetchone()[0]
    assert "65 unchanged" in rm(capsys, dbp, "import", PLAN, "--progress", PROG, "--gates", REAL_GATES)[1]
    assert c.execute("SELECT sum(version) FROM item").fetchone()[0] == v and c.execute("SELECT count(*) FROM audit").fetchone()[0] == n + 1
    # the step imported in review can be approved by someone else with the normal verb
    rid = items["1.1"]["id"]
    assert run(capsys, "item", "approve", rid, "--as", "user", "--db", dbp)[0] == 0 and c.execute("SELECT status FROM item WHERE id=?", (rid,)).fetchone()[0] == "done"


@real
def test_real_check_and_api(tmp_path, dbp, capsys):
    rm(capsys, dbp, "import", PLAN, "--progress", PROG, "--gates", REAL_GATES)
    rc, out = rm(capsys, dbp, "check")
    assert rc == 0 and "r: 4/65 steps done" in out and "phase 0: 4/4" in out and "phase 4: 0/18" in out and "gate G0 (phases 0): 4/4 [passed]" in out and "gate G2 (phases 3,4): 0/26 [open]" in out
    j = json.loads(rm(capsys, dbp, "check", "--json")[1])
    assert j["progress"]["done"] == 4 and j["progress"]["total"] == 65 and j["stale"] == j["orphan"] == j["blocked"] == []
    assert rm(capsys, dbp, "check")[0] == 0 and run(capsys, "roadmap", "check", "--project", "p", "--roadmap", "nope", "--db", dbp)[0] == 1
    srv = server.make_server(dbp, "p", 0); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    get = lambda q: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/roadmap?{q}").read())
    try:
        assert get("project=p")[0]["roadmap"] == "r"
        d = get("project=p&roadmap=r")
        assert set(d) >= {"project", "roadmap", "title", "version", "plan", "steps", "gates", "progress"} and len(d["steps"]) == 65 and [g["key"] for g in d["gates"]] == ["G0", "G1", "G2", "G3", "G4"]
        s = d["steps"][0]; assert {"key", "phase", "title", "body", "proof", "status", "state", "owner", "reviewer", "evidence", "note", "stale", "orphan"} <= set(s) and s["key"] == "0.1"
        assert d["gates"][0]["status"] == "done" and (d["gates"][1]["done"], d["gates"][1]["total"]) == (0, 13) and d["progress"]["done"] == 4
        assert get("project=p&roadmap=r&only=version") == {"version": d["version"]}
        # a step moves through the item verbs -> the version changes and the API shows it
        sid = next(x["id"] for x in d["steps"] if x["key"] == "1.2")
        for argv in (["claim", sid, "--as", "ann"], ["submit", sid, "--note", "e", "--as", "ann"]): run(capsys, "item", *argv, "--db", dbp)
        d2 = get("project=p&roadmap=r"); assert d2["version"] != d["version"] and next(x for x in d2["steps"] if x["key"] == "1.2")["status"] == "review"
        for bad in ("roadmap=r", "project=p&roadmap=zzz"):
            with pytest.raises(urllib.error.HTTPError): get(bad)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/roadmap?project=p", method="POST")
        with pytest.raises(urllib.error.HTTPError): urllib.request.urlopen(req)
    finally: srv.shutdown()


def test_gates_sources_and_removal(tmp_path, dbp, capsys):
    f, plan = mini(tmp_path); rm(capsys, dbp, "import", f); c = db.connect(dbp)  # plan key
    assert item(c, "G0", "gate") and item(c, "G1", "gate")["spec"]["phases"] == [1]
    del plan["gates"]; put(f, plan)  # no key, no flag: G0/G1 no longer declared -> rejected, none created
    rm(capsys, dbp, "import", f)
    assert {k: item(c, k, "gate")["status"] for k in ("G0", "G1")} == {"G0": "rejected", "G1": "rejected"}
    assert db.get_page(c, "p", "roadmap-r")["blocks"]["gates"] == []
    assert roadmap.check(c, "p", "r")["gates"] == []
    rm(capsys, dbp, "import", f, "--gates", "G2=0,1"); assert item(c, "G2", "gate")["spec"]["phases"] == [0, 1]  # flag
    plan["gates"] = {"G2": [0]}; put(f, plan); rm(capsys, dbp, "import", f, "--gates", "G2=1")  # plan key wins
    assert item(c, "G2", "gate")["spec"]["phases"] == [0]


def test_no_gates_and_done_gate_kept(tmp_path, dbp, capsys):
    f, plan = mini(tmp_path); g = plan.pop("gates"); put(f, plan); rm(capsys, dbp, "import", f)
    assert not c_gates(dbp) and rm(capsys, dbp, "import", f, "--gates", "bad")[0] == 1
    plan["gates"] = g; put(f, plan); rm(capsys, dbp, "import", f, "--progress", prog(tmp_path, **{"0.1": "done", "0.2": "done"}))
    c = db.connect(dbp); c.execute("UPDATE item SET status='done' WHERE kind='gate' AND json_extract(spec,'$.step_key')='G0'"); c.commit()
    del plan["gates"]; put(f, plan); rm(capsys, dbp, "import", f)
    assert item(c, "G0", "gate")["status"] == "done" and item(c, "G1", "gate")["status"] == "rejected"


def c_gates(dbp): return db.connect(dbp).execute("SELECT 1 FROM item WHERE kind='gate'").fetchall()


def test_minimal_plan_imports_and_serves(tmp_path, dbp, capsys):
    """Optional plan fields (meta, summary, progress, gate label, titles) may all be absent; the viewer defaults them."""
    f = tmp_path / "plan.json"
    f.write_text(json.dumps({"version": 1, "header": {"title": "Min"}, "sections": [{"id": "chi-tiet", "phases": [{"anchor": "p0", "title": "P0", "steps": [{"id": "0.1", "title": "S"}]}]}]}))
    assert rm(capsys, dbp, "import", f)[0] == 0
    srv = server.make_server(dbp, "p", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/roadmap?project=p&roadmap=r").read())
        assert [s["key"] for s in d["steps"]] == ["0.1"] and d["gates"] == [] and "summary" not in d["plan"]
    finally: srv.shutdown()
