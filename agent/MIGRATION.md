# Agent governance ownership

Endo owns `BOOTSTRAP.md`, `HIEN_PHAP.md`, agent roles, hooks, and maintained skills in this directory. Change governance here. Strata is a tool; its canonical usage manual remains `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md`. Endo references that manual without copying it. Tool commands, data formats and server role permissions remain Strata documentation; workflow policy belongs to Endo.

The previous paths under `/home/abel/project/tools/strata/agent/` are compatibility symlinks to Endo for bootstrap, constitution, roles, hooks and maintained skills. They contain no duplicate rule text. Existing installed links in `~/.claude` and `~/.codex` can continue resolving through them; this migration does not modify those installations. New installations should link directly to Endo as described in `BOOTSTRAP.md`. Keep the compatibility links until all installations have been updated.

`skills/schematic` is an external clone, excluded from Strata's git repository. Its existing directory is preserved in place; Endo links to it rather than copying its dependency tree or treating it as maintained governance. External pack skills remain in `~/.claude/packs/`.

Both repositories must be available at their documented paths for compatibility links and the external skill link to resolve. Strata executable, database and format-document paths remain in the Strata repository.
