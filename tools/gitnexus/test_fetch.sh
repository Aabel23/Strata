#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
tmp=$(mktemp -d)
trap 'python3 -c '\''import shutil, sys; shutil.rmtree(sys.argv[1])'\'' "$tmp"' EXIT

# An aliased source pointing back to the script directory must be rejected
# before any payload files are removed.
module="$tmp/module"
mkdir -p "$module/dist" "$module/scripts" "$module/vendor"
cp "$repo_dir/fetch.sh" "$module/fetch.sh"
printf '%s\n' '{' '  "version": "1.6.12",' '  "name": "gitnexus"' '}' > "$module/package.json"
printf 'keep\n' > "$module/dist/keep"

# A source nested in a directory the fetch will replace must also be rejected.
nested="$module/dist/nested-source"
mkdir -p "$nested/dist" "$nested/scripts" "$nested/vendor"
printf '%s\n' '{' '  "version": "1.6.12",' '  "name": "gitnexus"' '}' > "$nested/package.json"
printf 'nested source survives\n' > "$nested/dist/keep"
if bash "$module/fetch.sh" "$nested" >"$tmp/nested.out" 2>&1; then
  echo 'expected nested source to be rejected' >&2
  exit 1
fi
grep -q 'source must be outside the destination tree' "$tmp/nested.out" || {
  cat "$tmp/nested.out" >&2
  exit 1
}
[ -f "$nested/dist/keep" ]

ln -s "$module" "$tmp/module-alias"
if bash "$module/fetch.sh" "$tmp/module-alias" >"$tmp/same.out" 2>&1; then
  echo 'expected identical source and destination to fail' >&2
  exit 1
fi
grep -q 'source must be outside the destination tree' "$tmp/same.out" || {
  cat "$tmp/same.out" >&2
  exit 1
}
[ -f "$module/dist/keep" ]
[ -f "$module/package.json" ]

# Invocation through a symlink must still copy to the real script directory.
upstream="$tmp/upstream"
mkdir -p "$upstream/dist" "$upstream/scripts" "$upstream/vendor"
printf '%s\n' '{' '  "version": "1.6.12",' '  "name": "gitnexus"' '}' > "$upstream/package.json"
printf 'payload\n' > "$upstream/dist/payload"
ln -s "$module/fetch.sh" "$tmp/fetch-link"
bash "$tmp/fetch-link" "$upstream" >"$tmp/symlink.out"
grep -q "gitnexus 1.6.12 copied to $module" "$tmp/symlink.out"
[ -f "$module/dist/payload" ]
[ -d "$module/scripts" ]
[ -d "$module/vendor" ]

echo 'fetch.sh isolated tests passed'
