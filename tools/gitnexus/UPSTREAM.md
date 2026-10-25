# Upstream: GitNexus (vendored tool for agents)

- Package: `gitnexus` 1.6.12 (tag `v1.6.12`)
- Location: `tools/gitnexus`. Strata code never imports it; it is only called as a CLI/subprocess.
- The copy is produced by `fetch.sh` from the installed npm package and is gitignored (~121 MB). Only `LICENSE`, `UPSTREAM.md`, `fetch.sh`, `.gitignore` are tracked.
- Upstream repo: https://github.com/abhigyanpatwari/GitNexus
- LICENSE source: https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/v1.6.12/LICENSE
- License: PolyForm-Noncommercial-1.0.0 (noncommercial use only; keep `LICENSE` with any copy).
  **Strata cannot be used commercially while it includes GitNexus.**

## Notices
Upstream ships no NOTICE file. Required Notice: Copyright Abhigyan Patwari (https://github.com/abhigyanpatwari/GitNexus)

## Copied (byte-identical) by `fetch.sh`
`package.json`, `dist/`, `scripts/`, `vendor/` (without `vendor/*/prebuilds/`).

## Dropped
- `web/`: GitNexus UI, not used.
- `hooks/`, `skills/`, `README.md`: editor integration / docs, not used.
- `node_modules/`: rebuilt by the install below.
- `vendor/*/prebuilds/` (~100 MB, 6 platforms): grammars are rebuilt from source instead.

## Why vendor grammar src is kept
`vendor/*/src` (~100 MB, generated `parser.c`) lets the postinstall run `node-gyp rebuild` when no prebuild exists.

## Install (NOT RUN; needs user approval)
```
cd tools/gitnexus && SCARF_ANALYTICS=false npm install --omit=dev
```
- `@scarf/scarf` postinstall sends install analytics unless disabled; the env var above disables it.
- Grammar build needs gcc/g++/make/python3 and fails silently. Check: `ls vendor/*/build/Release/*.node`

## Local patches
none. Never edit; re-run `fetch.sh` (re-copy) to upgrade.
