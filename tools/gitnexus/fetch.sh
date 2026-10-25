#!/usr/bin/env bash
# Copy the pinned GitNexus payload from an installed npm package. Never runs npm install.
set -euo pipefail
WANT=1.6.12
dst=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
src=${1:-${GITNEXUS_SRC:-$(npm root -g)/gitnexus}}
[ -f "$src/package.json" ] || { echo "no package.json in $src" >&2; exit 1; }
have=$(sed -n 's/^  "version": "\(.*\)",$/\1/p' "$src/package.json" | head -n1)
[ "$have" = "$WANT" ] || { echo "version $have, need exactly $WANT" >&2; exit 1; }
rm -rf "$dst/dist" "$dst/scripts" "$dst/vendor"
cp "$src/package.json" "$dst/package.json"
cp -r "$src/dist" "$src/scripts" "$dst/"
mkdir "$dst/vendor"
for d in "$src"/vendor/*; do
  [ -e "$d" ] || continue
  mkdir "$dst/vendor/$(basename "$d")"
  for e in "$d"/* "$d"/.[!.]*; do
    [ -e "$e" ] || continue
    [ "$(basename "$e")" = prebuilds ] || cp -r "$e" "$dst/vendor/$(basename "$d")/"
  done
done
echo "gitnexus $WANT copied to $dst"
