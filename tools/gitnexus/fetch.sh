#!/usr/bin/env bash
# Copy the pinned GitNexus payload from an installed npm package. Queries `npm root -g` when no source is given; never runs `npm install`.
set -euo pipefail
WANT=1.6.12
script=${BASH_SOURCE[0]}
while [ -L "$script" ]; do
  script_dir=$(cd -P "$(dirname "$script")" && pwd)
  target=$(readlink "$script")
  case "$target" in
    /*) script=$target ;;
    *) script=$script_dir/$target ;;
  esac
done
dst=$(cd -P "$(dirname "$script")" && pwd)
src=${1:-${GITNEXUS_SRC:-$(npm root -g)/gitnexus}}
[ -f "$src/package.json" ] || { echo "no package.json in $src" >&2; exit 1; }
src=$(cd -P "$src" && pwd)
case "$src" in
  "$dst"|"$dst"/*)
    echo "source must be outside the destination tree: $src" >&2
    exit 1
    ;;
esac
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
