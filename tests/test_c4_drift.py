import json
import sqlite3
import subprocess

from conftest import run


def test_drift_reports_only_tracked_cross_app_edges(tmp_path, dbp):
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg/__init__.py").write_text("package = True\n")
    (root / "pkg/a.py").write_text("from pkg import b, c\n")
    (root / "pkg/only_init.py").write_text("import pkg\n")
    (root / "pkg/b.py").write_text("value = 1\n")
    (root / "pkg/c.py").write_text("value = 2\n")
    (root / "pkg/orphan.py").write_text("value = 3\n")
    (root / "pkg/future_owned.py").write_text("value = 4\n")
    (root / "web").mkdir()
    (root / "web/index.html").write_text('<script src="/web/main.js"></script>\n<!-- <script src="/web/fake.js"></script> -->\n')
    (root / "web/main.js").write_text("import './dep.js'; // import './fake.js';\nconst note = \"require('./fake.js')\";\n")
    (root / "web/dep.js").write_text("export const value = 1;\n")
    (root / "web/fake.js").write_text("export const ignored = true;\n")
    (root / "viewer").mkdir()
    (root / "viewer/page.html").write_text('<script src="/app.js"></script>\n')
    (root / "viewer/app.js").write_text("export const mounted = true;\n")
    (tmp_path / "outside.js").write_text("export const outside = true;\n")
    (root / "tests").mkdir()
    (root / "tests/test_ignored.py").write_text("import pkg.b\n")
    (root / "vendor").mkdir()
    (root / "vendor/ignored.min.js").write_text("import './x.js'\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "pkg", "web", "viewer", "tests", "vendor"], check=True)

    c = sqlite3.connect(dbp)
    from strata.db import init, add_project
    c.close()
    c = init(dbp)
    add_project(c, "p", "P", str(root))
    c.execute("INSERT INTO c4_meta(project,name,root) VALUES('p','P',?)", (str(root),))
    objects = [
        ("app_a", "app", None, "[]"), ("app_b", "app", None, "[]"),
        ("app_c", "app", None, "[]"), ("app_d", "app", None, "[]"), ("app_e", "app", None, "[]"), ("app_f", "app", None, "[]"),
        ("app_g", "app", None, "[]"), ("app_h", "app", None, "[]"), ("app_i", "app", None, "[]"),
        ("a", "component", "app_a", '["pkg/a.py"]'),
        ("b", "component", "app_b", '["pkg/b.py", "pkg/__init__.py"]'),
        ("c", "component", "app_f", '["pkg/c.py"]'),
        ("only_init", "component", "app_i", '["pkg/only_init.py"]'),
        ("web_main", "component", "app_c", '["web/index.html", "web/main.js"]'),
        ("web_dep", "component", "app_d", '["web/dep.js"]'),
        ("web_fake", "component", "app_e", '["web/fake.js"]'),
        ("viewer_page", "component", "app_g", '["viewer/page.html"]'),
        ("viewer_app", "component", "app_h", '["viewer/app.js"]'),
        ("stale", "component", "app_a", '["gone/*.py"]'),
        ("future", "component", "app_a", '["future.py"]'),
        ("future_owns", "component", "app_a", '["pkg/future_owned.py"]'),
        ("no_owns", "component", "app_a", "[]"),
    ]
    for oid, kind, parent, owns in objects:
        c.execute("INSERT INTO c4_object(project,id,type,name,kind,parent,status,owns) VALUES('p',?,?,?,?,?,?,?)",
                  (oid, kind, oid, kind, parent, "future" if oid in ("future", "future_owns") else "live", owns))
    c.execute("INSERT INTO c4_connection(project,id,from_id,to_id,status) VALUES('p','ba','b','a','live')")
    c.commit()
    c.close()

    rc, out = run(dbp, "c4", "drift", "--project", "p", "--json", "--db", str(dbp))
    assert rc == 0
    data = json.loads(out)
    assert data["undeclared_edges"] == [{"from": "app_a", "to": "app_b"}, {"from": "app_a", "to": "app_f"}, {"from": "app_c", "to": "app_d"}, {"from": "app_g", "to": "app_h"}, {"from": "app_i", "to": "app_b"}]
    assert data["declared_without_code_edge"] == [{"link": "ba", "from": "app_b", "to": "app_a"}]
    assert data["unowned_files"] == ["pkg/future_owned.py", "pkg/orphan.py"]
    assert data["stale_owns"] == [{"object": "future", "entry": "future.py"}, {"object": "stale", "entry": "gone/*.py"}]
    assert data["stats"]["code_import_edges"] == 7
    from strata.c4_drift import _resolve
    assert _resolve(root, "viewer/page.html", "/../../outside.js") is None

    rc, out = run(dbp, "c4", "drift", "--project", "p", "--fail-on-undeclared", "--db", str(dbp))
    assert rc == 1 and "pkg/orphan.py" in out and "app_a -> app_b" in out and "app_a -> app_f" in out and "app_c -> app_d" in out and "app_g -> app_h" in out and "app_i -> app_b" in out
