#!/usr/bin/env bash
# Put `strata` on your PATH: symlink ~/.local/bin/strata -> <repo>/strata.py. No sudo.
set -e
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
command -v python3 >/dev/null || { echo "python3 is missing. Install Python 3 first (e.g. sudo apt install python3)."; exit 1; }
python3 -c "import yaml" 2>/dev/null || { echo "PyYAML is missing. Fix with: pip install --user pyyaml"; exit 1; }
chmod +x "$repo/strata.py"
bin="$HOME/.local/bin"; mkdir -p "$bin"
dest="$repo/strata.py"; link="$bin/strata"
if [ "$(readlink "$link" 2>/dev/null)" = "$dest" ]; then echo "Already installed: $link"; exit 0
elif [ -e "$link" ] || [ -L "$link" ]; then
  if [ "$1" != "--force" ]; then
    echo "Not touching $link: it already exists ($(ls -ld "$link" | cut -d' ' -f1,9-))."
    echo "To replace it with this install, run: bash scripts/install.sh --force"; exit 1
  fi
  echo "replacing $link -> $(readlink "$link" || echo 'regular file')"
fi
ln -sf "$dest" "$link"; echo "Installed: $link -> $dest"
case ":$PATH:" in *":$bin:"*) ;; *) echo "WARNING: $bin is not on your PATH. Add to ~/.bashrc: export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
cat <<M

Next steps:
  cd your-project && strata init
  strata serve        (or: systemctl --user start strata, if you set up the service)
  strata open
M
