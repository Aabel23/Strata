#!/usr/bin/env bash
# Rebase, check, and locally fast-forward a task branch. Never pushes.
# Exit: 0 landed, 2 usage/dirty checkout, 3 path overlap, 4 verify failed,
# 5 rebase conflict, 6 retries exhausted.
set -euo pipefail

usage() { echo "usage: land.sh --repo <main checkout> --branch <task branch> --base <base commit> [--worktree <dir>] [--retries N] -- <verify command...>" >&2; exit 2; }
repo= branch= base= wt= retries=3
while [ $# -gt 0 ]; do
  case $1 in
    --repo) [ $# -ge 2 ] || usage; repo=$2; shift 2 ;;
    --branch) [ $# -ge 2 ] || usage; branch=$2; shift 2 ;;
    --base) [ $# -ge 2 ] || usage; base=$2; shift 2 ;;
    --worktree) [ $# -ge 2 ] || usage; wt=$2; shift 2 ;;
    --retries) [ $# -ge 2 ] || usage; retries=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done
[ -n "$repo" ] && [ -n "$branch" ] && [ -n "$base" ] && [ $# -gt 0 ] || usage
case $retries in ''|*[!0-9]*) usage ;; esac

main=$(git -C "$repo" symbolic-ref --short HEAD 2>/dev/null) || { echo "main checkout must be on a branch" >&2; exit 2; }
main_ref="refs/heads/$main"
if [ -n "$(git -C "$repo" status --porcelain)" ]; then
  echo "main worktree $repo has uncommitted changes; clean it before landing" >&2; exit 2
fi
if [ -n "$wt" ]; then
  [ "$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null || true)" = "$branch" ] || { echo "worktree $wt is not on branch $branch" >&2; exit 2; }
else
  wt=$(git -C "$repo" worktree list --porcelain | awk -v b="refs/heads/$branch" '/^worktree /{w=substr($0,10)} $0=="branch " b{print w}')
  [ -n "$wt" ] || { echo "no worktree has $branch checked out; pass --worktree" >&2; exit 2; }
fi
[ "$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null || true)" = "$branch" ] || { echo "worktree $wt is not on branch $branch" >&2; exit 2; }
[ -z "$(git -C "$wt" status --porcelain)" ] || { echo "task worktree $wt has uncommitted changes; commit first" >&2; exit 2; }
git -C "$repo" rev-parse --verify "$base^{commit}" >/dev/null 2>&1 || { echo "base is not a commit" >&2; exit 2; }
git -C "$repo" merge-base --is-ancestor "$base" "$branch" || { echo "task branch does not descend from base" >&2; exit 2; }

# Keep path sets NUL-delimited internally so filenames with whitespace remain safe.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

for ((i = 0; i <= retries; i++)); do
  [ -z "$(git -C "$repo" status --porcelain)" ] || { echo "main worktree $repo became dirty; refusing to land" >&2; exit 2; }
  current=$(git -C "$repo" rev-parse "$main_ref")
  # Compare task-only changes against the merge base with observed main. This
  # remains correct when the worker has already rebased and base..branch now
  # contains commits that were made by other coders on main.
  git -C "$repo" diff --no-renames --name-only -z "$current...$branch" >"$tmp/task"
  git -C "$repo" diff --no-renames --name-only -z "$base..$current" >"$tmp/main"
  overlap=$(python3 - "$tmp/task" "$tmp/main" <<'PY'
import os, sys
def read(p):
    with open(p, 'rb') as f:
        return [x.decode(errors='surrogateescape') for x in f.read().split(b'\0') if x]
t, m = read(sys.argv[1]), read(sys.argv[2])
hits = set()
for a in t:
    for b in m:
        if a == b or a.startswith(b.rstrip('/') + '/') or b.startswith(a.rstrip('/') + '/'):
            hits.update((a, b))
for p in sorted(hits): print(p)
PY
)
  if [ -n "$overlap" ]; then
    echo "path overlap with $main since $base:" >&2; printf '%s\n' "$overlap" >&2; exit 3
  fi

  # Refresh task tip after each retry and rebase it onto the exact observed main tip.
  if ! git -C "$wt" rebase "$current" >/dev/null 2>&1; then
    git -C "$wt" rebase --abort >/dev/null 2>&1 || true
    echo "rebase conflict onto $main" >&2; exit 5
  fi
  (cd "$wt" && "$@") || { echo "verify failed: $*" >&2; exit 4; }
  [ "$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null || true)" = "$branch" ] || { echo "verify changed the task worktree branch" >&2; exit 2; }
  [ -z "$(git -C "$wt" status --porcelain)" ] || { echo "task worktree $wt became dirty during verify" >&2; exit 2; }

  # Verify and merge against the same main tip. A move during verification retries
  # after a fresh overlap check/rebase/verification. The status check protects local edits.
  [ -z "$(git -C "$repo" status --porcelain)" ] || { echo "main worktree $repo became dirty; refusing to land" >&2; exit 2; }
  now=$(git -C "$repo" rev-parse "$main_ref")
  if [ "$now" != "$current" ]; then
    echo "$main moved during verify; retry $((i + 1))/$retries" >&2
    continue
  fi
  if ! git -C "$repo" merge-base --is-ancestor "$current" "$branch"; then
    echo "task branch is no longer based on observed main tip" >&2; exit 5
  fi
  if ! git -C "$repo" merge --ff-only "$branch" >/dev/null; then
    echo "$main moved during merge; retry $((i + 1))/$retries" >&2
    continue
  fi
  echo "landed $(git -C "$repo" rev-parse --short "$branch") on $main"
  exit 0
done
echo "retries exhausted" >&2; exit 6
