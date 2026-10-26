#!/usr/bin/env bash
# Parallel-coder integration tests using throwaway repositories only.
set -uo pipefail
LAND=$(cd "$(dirname "$0")" && pwd)/land.sh
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t
R=$T/main; fails=0
g() { git -C "$R" "$@"; }
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (got '$2', want '$3')"; fails=1; fi; }
git init -q -b main "$R"; echo seed >"$R/seed"; g add .; g commit -qm base
BASE=$(g rev-parse HEAD)
task() { local n=$1; shift; g worktree add -q -b "t$n" "$T/wt$n" "$BASE"
  for f in "$@"; do mkdir -p "$(dirname "$T/wt$n/$f")"; echo "$n" >"$T/wt$n/$f"; git -C "$T/wt$n" add "$f"; done
  git -C "$T/wt$n" commit -qm "task $n"; }
land() { local n=$1; shift; "$LAND" --repo "$R" --branch "t$n" --base "$BASE" --worktree "$T/wt$n" -- "$@" 2>"$T/err"; }

# Three independent coders start from the same base. Two land; the third collides.
task A src/a.py; task B docs/b.md; task C src/a.py
old=$(g rev-parse HEAD); land A true; rc=$?
check "coder A lands" "$rc" 0
g merge-base --is-ancestor "$old" main && ff=ok || ff=no; check "coder A lands by fast-forward" "$ff" ok
old=$(g rev-parse HEAD); land B true; rc=$?
check "disjoint coder B rebases and lands" "$rc" 0
g merge-base --is-ancestor "$old" main && ff=ok || ff=no; check "coder B lands by fast-forward" "$ff" ok
land C true; rc=$?
check "overlapping coder C is rejected" "$rc" 3
check "overlap identifies path" "$(grep -c '^src/a.py$' "$T/err")" 1
# Resolve by rebasing onto main, dropping the now-duplicate overlapping change,
# then implement the task on a disjoint path.
git -C "$T/wtC" rebase main >/dev/null 2>&1; rebase_rc=$?
if [ "$rebase_rc" -ne 0 ]; then git -C "$T/wtC" rebase --skip >/dev/null; fi
mkdir -p "$T/wtC/src"; echo C >"$T/wtC/src/c.py"; git -C "$T/wtC" add src/c.py; git -C "$T/wtC" commit -qm 'resolve scope overlap'
land C true; rc=$?
check "resolved coder C lands" "$rc" 0

# Directory/ancestor collisions and dirty-checkout refusal.
task D tree/leaf.txt; echo file >"$R/tree"; g add tree; g commit -qm 'main file ancestor'
land D true; rc=$?; check "ancestor overlap rejected" "$rc" 3
task E clean.txt; echo dirty >>"$T/wtE/clean.txt"; land E true; rc=$?
check "dirty task worktree rejected" "$rc" 2
old=$(g rev-parse HEAD); echo dirty >>"$R/seed"; land E true; rc=$?
check "dirty main rejected" "$rc" 2
git -C "$R" checkout -- seed
check "dirty-main refusal leaves HEAD unchanged" "$(g rev-parse HEAD)" "$old"
task G verify.txt; old=$(g rev-parse HEAD); land G false; rc=$?
check "failed verification rejected" "$rc" 4
check "failed verification leaves main unchanged" "$(g rev-parse HEAD)" "$old"

# A verify command advances main exactly once. The script must retry, recheck,
# rebase and verify again before landing.
task F retry/f.txt
cat >"$T/verify-move-once" <<'SH'
#!/usr/bin/env bash
if [ ! -e "$MOVE_MARK" ]; then
  touch "$MOVE_MARK"
  echo parallel >"$MAIN_REPO/parallel.txt"
  git -C "$MAIN_REPO" add parallel.txt
  git -C "$MAIN_REPO" commit -qm 'parallel coder landed during verify'
fi
SH
chmod +x "$T/verify-move-once"
export MOVE_MARK="$T/moved" MAIN_REPO="$R"
land F "$T/verify-move-once"; rc=$?
check "moved-main retry succeeds" "$rc" 0
check "verify reran after main moved" "$(grep -c 'moved during verify' "$T/err")" 1
g show main:parallel.txt >/dev/null 2>&1 && check "parallel main commit preserved" yes yes || check "parallel main commit preserved" no yes
check "no merge commits" "$(g rev-list --merges main | wc -l | tr -d ' ')" 0
exit "$fails"
