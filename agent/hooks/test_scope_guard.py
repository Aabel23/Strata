#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_guard.py")

def run(tool, path, cwd):
    p = subprocess.run([sys.executable, HOOK], text=True, capture_output=True,
                       input=json.dumps({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": cwd}))
    return p.returncode

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" (got {got}, want {want})"))

with tempfile.TemporaryDirectory() as t:
    t = os.path.realpath(t)
    free = os.path.join(t, "free"); os.makedirs(free)
    check("no .task-scope allows", run("Write", "x.txt", free), 0)
    w = os.path.join(t, "wt"); os.makedirs(os.path.join(w, "src/sub")); os.makedirs(os.path.join(w, "other"))
    outside = os.path.join(t, "outside"); os.makedirs(outside)
    with open(os.path.join(w, ".task-scope"), "w") as f:
        f.write("# c\n\nREADME.md\nsrc\n")
    os.symlink(outside, os.path.join(w, "src/link"))
    check("allowed file", run("Edit", "README.md", w), 0)
    check("allowed dir (new file)", run("Write", os.path.join(w, "src/sub/new.py"), w), 0)
    check("outside blocked", run("Edit", "other/a.py", w), 2)
    check("sibling prefix blocked", run("Edit", "src2/a.py", w), 2)
    check("../ escape blocked", run("Edit", "src/../other/a.py", w), 2)
    check("symlink escape blocked", run("Write", "src/link/evil.py", w), 2)
    check(".task-scope blocked", run("Write", ".task-scope", w), 2)
    check("non-edit tool allowed", run("Bash", "other/a.py", w), 0)
    main = os.path.join(t, "maincheckout"); os.makedirs(main)
    check("cwd scoped + absolute target outside blocked", run("Write", os.path.join(main, "x.py"), w), 2)
    os.symlink(os.path.join(w, "src"), os.path.join(t, "inlink"))
    os.symlink(os.path.join(w, "other"), os.path.join(t, "badlink"))
    check("outside symlink -> allowed dir allowed", run("Write", os.path.join(t, "inlink/n.py"), w), 0)
    check("outside symlink -> disallowed dir blocked", run("Write", os.path.join(t, "badlink/n.py"), w), 2)
    bad = os.path.join(t, "bad"); os.makedirs(bad)
    with open(os.path.join(bad, ".task-scope"), "wb") as f:
        f.write(b"\xff\xfe\x80")
    check("undecodable .task-scope blocked", run("Write", "a.py", bad), 2)
    unread = os.path.join(t, "unread"); os.makedirs(unread)
    open(os.path.join(unread, ".task-scope"), "w").write("a.py\n")
    os.chmod(os.path.join(unread, ".task-scope"), 0)
    if os.access(os.path.join(unread, ".task-scope"), os.R_OK):
        print("SKIP unreadable .task-scope (running as root)")
    else:
        check("unreadable .task-scope blocked", run("Write", "a.py", unread), 2)
    check("MultiEdit outside blocked", run("MultiEdit", "other/a.py", w), 2)
sys.exit(1 if fails else 0)
