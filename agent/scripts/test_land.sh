#!/usr/bin/env bash
# Throwaway-repo tests for land.sh. Prints PASS/FAIL per case; non-zero exit on any FAIL.
set -uo pipefail
LAND=$(cd "$(dirname "$0")" && pwd)/land.sh
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
R=$T/main; fails=0
g() { git -C "$R" "$@"; }
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (got '$2', want '$3')"; fails=1; fi; }

git init -q -b main "$R"; echo base >"$R/a.txt"; echo base >"$R/b.txt"; echo base >"$R/h.txt"
g add .; g commit -qm base
BASE=$(g rev-parse HEAD)

# task NAME FILE...: branch off BASE in its own worktree, commit each file.
task() { n=$1; shift; g worktree add -q -b "t$n" "$T/wt$n" "$BASE"
  for f in "$@"; do mkdir -p "$(dirname "$T/wt$n/$f")"; echo "$n" >"$T/wt$n/$f"; git -C "$T/wt$n" add "$f"; done
  git -C "$T/wt$n" commit -qm "task $n"; }
land() { n=$1; shift; "$LAND" --repo "$R" --branch "t$n" --base "$BASE" --worktree "$T/wt$n" -- "$@" 2>"$T/err"; }

task I h.txt
task A a.txt; task B b.txt; task C a.txt; task D d/x.txt; task E e.txt; task F f.txt

old=$(g rev-parse HEAD); land A true; rc=$?
check "A lands" "$rc" 0
g merge-base --is-ancestor "$old" main && ff=ok || ff=no; check "A is fast-forward" "$ff" ok

old=$(g rev-parse HEAD); land B true; rc=$?
check "B (disjoint, same base) lands after rebase" "$rc" 0
g merge-base --is-ancestor "$old" main && ff=ok || ff=no; check "B is fast-forward" "$ff" ok
check "main has both A and B files" "$(g show main:a.txt)/$(g show main:b.txt)" "A/B"

land C true; rc=$?
check "C (same file as A) exits 3" "$rc" 3
check "C names the path" "$(grep -c '^a.txt$' "$T/err")" 1

# dir-vs-file: main gets file "d", task D adds "d/x.txt"
echo f >"$R/d"; g add d; g commit -qm "file d"
land D true; rc=$?
check "D (dir vs file) exits 3" "$rc" 3
check "D names the path" "$(grep -c '^d' "$T/err")" 2

old=$(g rev-parse HEAD); land E false; rc=$?
check "E verify failure exits 4" "$rc" 4
check "main unchanged after verify failure" "$(g rev-parse HEAD)" "$old"

echo dirty >>"$T/wtF/f.txt"; land F true; rc=$?
check "F dirty worktree refused" "$rc" 2
check "main unchanged after dirty refusal" "$(g rev-parse HEAD)" "$old"

# rename: main renames h.txt (task I edits it) -> overlap on the old path
g mv h.txt h2.txt; g commit -qm rename
land I true; rc=$?
check "I (main renamed its file) exits 3" "$rc" 3
check "I names the old path" "$(grep -c '^h.txt$' "$T/err")" 1
"$LAND" --repo "$R" --branch tF --base "$BASE" --worktree "$T/wtI" -- true 2>/dev/null; rc=$?
check "worktree on wrong branch exits 2" "$rc" 2

check "main history has no merge commits" "$(g rev-list --merges main | wc -l | tr -d ' ')" 0
exit $fails
