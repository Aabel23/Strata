import json, shutil, sqlite3, yaml
import pytest
from strata import db, roadmap, service
from test_roadmap import run, rm, dbp, item  # noqa: F401  (dbp fixture)


def setup_objs(dbp, *objs):
    c = db.connect(dbp)
    for o in objs: c.execute("INSERT INTO c4_object(id,project,type,name) VALUES(?,?,?,?)", (o, "p", "component", o))
    c.commit(); return c


def crit(id, by="machine", level="core"):
    return {"id": id, "category": "tài liệu", "text": "t", "verify": "v", "confirm_by": by, "level": level}


def yml(tmp_path, **over):
    y = {"title": "T", "phases": [
        {"n": 1, "title": "One", "goal": "g1", "level": "skeleton", "blocks": [{"object": "a", "intent": "build"}],
         "criteria": [crit("c1"), crit("cu", "user"), crit("co", level="optional")], "steps": [{"id": "1.1", "title": "S", "proof": "x"}]},
        {"n": 2, "title": "Two", "goal": "g2", "level": "demo", "blocks": [{"object": "b", "intent": "extend"}], "criteria": [], "steps": []}]}
    y.update(over); f = tmp_path / "r.yaml"; f.write_text(yaml.safe_dump(y, allow_unicode=True)); return f


def test_import_yaml_stores_phases_and_checks_blocks(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); f = yml(tmp_path)
    assert rm(capsys, dbp, "import", f)[0] == 0
    assert item(c, "1.1")["spec"]["phase"] == 1 and item(c, "G1", "gate") and item(c, "G2", "gate")
    d = roadmap._def(c, "p", "r"); assert [p["n"] for p in d["phases"]] == [1, 2] and d["phases"][0]["blocks"][0]["planned_phase"] == 1
    bad = yml(tmp_path, phases=[{**yaml.safe_load(f.read_text())["phases"][0], "blocks": [{"object": "nope", "intent": "build"}]}])
    rc, out = rm(capsys, dbp, "import", bad)
    assert rc == 1 and "'nope' is not a C4 object" in out


def test_init_template_has_docs_criteria_every_phase(tmp_path, dbp, capsys):
    c = db.connect(dbp); c.execute("UPDATE project SET docs_dir=? WHERE id='p'", (str(tmp_path / "docs"),)); c.commit()
    assert rm(capsys, dbp, "init", "--template", "five-phase")[0] == 0
    y = yaml.safe_load((tmp_path / "docs" / "plan" / "r.yaml").read_text())
    assert [p["level"] for p in y["phases"]] == ["skeleton", "demo", "hardened", "staging", "release"]
    assert all(any(x["category"] == "tài liệu" for x in p["criteria"]) for p in y["phases"])
    assert rm(capsys, dbp, "init", "--template", "five-phase")[0] == 1  # no overwrite
    assert rm(capsys, dbp, "import", tmp_path / "docs" / "plan" / "r.yaml")[0] == 0  # template imports as is


def test_criterion_who_and_audit(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); rm(capsys, dbp, "import", yml(tmp_path))
    cs = lambda *a: run(capsys, "roadmap", "criterion", "set", "r", *a, "--project", "p", "--db", dbp)
    rc, out = cs("cu", "--result", "pass", "--as", "reviewer"); assert rc == 1 and "user" in out
    assert cs("cu", "--result", "pass", "--value", "ok", "--as", "user")[0] == 0
    assert cs("c1", "--result", "pass", "--value", "9", "--as", "machine")[0] == 0
    r = [x for p in roadmap._def(c, "p", "r")["phases"] for x in p["criteria"] if x["id"] == "cu"][0]["result"]
    assert r["result"] == "pass" and r["value"] == "ok" and r["by"] == "user"
    assert c.execute("SELECT count(*) FROM audit WHERE tool='roadmap.criterion'").fetchone()[0] == 2
    assert c.execute("SELECT count(*) FROM audit WHERE tool='denied:roadmap.criterion'").fetchone()[0] == 1
    assert cs("c1", "--waive", "why", "--as", "machine")[0] == 1


def test_gate_needs_steps_criteria_tasks_or_waive(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); rm(capsys, dbp, "import", yml(tmp_path))
    gp = lambda: rm(capsys, dbp, "gate", "pass", "G1", "--as", "user")
    cs = lambda *a: run(capsys, "roadmap", "criterion", "set", "r", *a, "--project", "p", "--db", dbp)
    sid = item(c, "1.1")["id"]
    for argv in (["claim", sid, "--as", "ann"], ["submit", sid, "--note", "e", "--as", "ann"], ["approve", sid, "--as", "bob"]): run(capsys, "item", *argv, "--db", dbp)
    rc, out = gp(); assert rc == 1 and "criterion c1" in out and "criterion cu" in out and "block a has no task" in out and "co" not in out.split("open:")[1].replace("criterion", "")
    cs("c1", "--result", "pass", "--as", "machine"); cs("cu", "--waive", "chấp nhận", "--as", "user")
    t = service.add_item(c, "main", "p", "task", "build a", status="open"); db.link(c, "p", "a", item=t)
    rc, out = gp(); assert rc == 1 and f"task #{t}" in out
    c.execute("UPDATE item SET status='done' WHERE id=?", (t,)); c.commit()
    assert gp()[0] == 0 and item(c, "G1", "gate")["status"] == "done"


def test_phase_label_default_and_off_roadmap(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); rm(capsys, dbp, "import", yml(tmp_path))
    bug = service.add_item(c, "coder", "p", "issue", "bug")
    t1 = service.add_item(c, "main", "p", "task", "later", phase=2)
    t0 = service.add_item(c, "main", "p", "task", "free")
    rows = {r["id"]: r for r in roadmap.annotate(c, service.list_items(c, "p"))}
    assert (rows[bug]["phase"], rows[bug]["roadmap"], rows[bug]["off_roadmap"]) == (1, "r", False)
    assert rows[t1]["phase"] == 2 and rows[t1]["off_roadmap"] is True and rows[t0]["phase"] is None and rows[t0]["off_roadmap"] is False
    assert run(capsys, "item", "add", "--project", "p", "--kind", "task", "--title", "x", "--phase", "1", "--db", dbp)[0] == 0
    assert run(capsys, "item", "edit", t0, "--phase", "2", "--db", dbp)[0] == 0 and service.get_item(c, t0)["phase"] == 2


def test_pull_moves_block_and_tasks(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); rm(capsys, dbp, "import", yml(tmp_path))
    t = service.add_item(c, "main", "p", "task", "do b", phase=2); db.link(c, "p", "b", item=t)
    assert rm(capsys, dbp, "pull", "b", "--to", "1", "--note", "need early")[0] == 0
    assert service.get_item(c, t)["phase"] == 1
    p1 = roadmap._def(c, "p", "r")["phases"][0]; b = [x for x in p1["blocks"] if x["object"] == "b"][0]
    assert b["planned_phase"] == 2 and b["pulled_from"] == 2
    a = json.loads(c.execute("SELECT after FROM audit WHERE tool='roadmap.pull'").fetchone()[0]); assert a["note"] == "need early" and a["items"] == [t]
    rm(capsys, dbp, "import", tmp_path / "r.yaml")  # re-import keeps the pull
    assert [x["object"] for x in roadmap._def(c, "p", "r")["phases"][0]["blocks"]] == ["a", "b"]
    assert rm(capsys, dbp, "pull", "b", "--to", "1", "--note", "n")[0] == 1


def test_api_phases(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); rm(capsys, dbp, "import", yml(tmp_path))
    t = service.add_item(c, "main", "p", "task", "do a", phase=1); db.link(c, "p", "a", item=t)
    out = roadmap.api(c, "p", "r"); ph = out["phases"][0]
    assert out["current_phase"] == 1 and ph["current"] and ph["goal"] == "g1" and ph["level"] == "skeleton"
    assert (ph["blocks"][0]["done"], ph["blocks"][0]["total"], ph["blocks"][0]["intent"]) == (0, 1, "build")
    assert ph["criteria"][0]["result"] is None and "criterion c1" in ph["gate"]["missing"] and out["off_roadmap"] == []
    assert json.loads(json.dumps(out))  # serialisable


def test_migration_adds_columns_with_backup(tmp_path):
    p = str(tmp_path / "old.db"); k = sqlite3.connect(p)
    from pathlib import Path
    k.executescript(db.SCHEMA.read_text().replace(",\n  phase INT, roadmap TEXT", "")); k.execute("INSERT INTO item(project,kind,title,status) VALUES('p','task','t','open')"); k.commit(); k.close()
    c = db.init(p)
    assert {"phase", "roadmap"} <= {r[1] for r in c.execute("PRAGMA table_info(item)")} and c.execute("SELECT count(*) FROM item").fetchone()[0] == 1
    assert list((tmp_path / "backups").glob("strata-*.db"))


def test_check_zero_step_roadmap_lists_gaps(tmp_path, dbp, capsys):
    c = setup_objs(dbp, "a", "b"); f = yml(tmp_path, phases=[{**yaml.safe_load(yml(tmp_path).read_text())["phases"][0], "steps": []}])
    assert rm(capsys, dbp, "import", f)[0] == 0
    rc, out = rm(capsys, dbp, "check")
    assert rc == 0 and "P1 skeleton: steps 0/0, core criteria 0/2 passed" in out and "criterion c1" in out and "block a has no task" in out
    rc, out = rm(capsys, dbp, "check", "--json")
    assert json.loads(out)["phases"][0]["gate"]["gaps"]
