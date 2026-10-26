#!/usr/bin/env bash
# Land a task branch onto main: overlap check, rebase, verify, ff-only merge. Local only, never pushes.
# Exit: 0 landed, 2 usage, 3 path overlap, 4 verify failed, 5 rebase conflict, 6 retries exhausted.
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

main=$(git -C "$repo" symbolic-ref --short HEAD)
if [ -z "$wt" ]; then
  wt=$(git -C "$repo" worktree list --porcelain | awk -v b="refs/heads/$branch" '/^worktree /{w=substr($0,10)} $0=="branch " b{print w}')
  [ -n "$wt" ] || { echo "no worktree has $branch checked out; pass --worktree" >&2; exit 2; }
fi

if [ "$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null)" != "$branch" ]; then
  echo "worktree $wt is not on branch $branch" >&2; exit 2
fi
if [ -n "$(git -C "$wt" status --porcelain)" ]; then
  echo "task worktree $wt has uncommitted changes; commit first" >&2; exit 2
fi

task_paths=$(git -C "$repo" diff --no-renames --name-only "$base..$branch")

for ((i = 0; i <= retries; i++)); do
  main_paths=$(git -C "$repo" diff --no-renames --name-only "$base..$main")
  overlap=$(awk 'NR==FNR{t[$0]=1; next} {m=$0; for (p in t) if (p==m || index(p"/", m"/")==1 || index(m"/", p"/")==1) {print p; if (p!=m) print m}}' \
    <(printf '%s\n' "$task_paths") <(printf '%s\n' "$main_paths") | sort -u | sed '/^$/d')
  if [ -n "$overlap" ]; then
    echo "path overlap with $main since $base:" >&2; echo "$overlap" >&2; exit 3
  fi

  if ! git -C "$wt" rebase "$main" >/dev/null 2>&1; then
    git -C "$wt" rebase --abort >/dev/null 2>&1 || true
    echo "rebase conflict onto $main" >&2; exit 5
  fi

  (cd "$wt" && "$@") || { echo "verify failed: $*" >&2; exit 4; }

  if git -C "$repo" merge-base --is-ancestor "$main" "$branch"; then
    git -C "$repo" merge --ff-only "$branch" >/dev/null
    echo "landed $(git -C "$repo" rev-parse --short "$main") on $main"
    exit 0
  fi
  echo "$main moved during verify; retry $((i + 1))/$retries" >&2
done
echo "retries exhausted" >&2; exit 6
