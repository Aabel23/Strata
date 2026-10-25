# Endo history

This directory preserves the original Endo design and Git history after its integration into Strata. Endo is now the agent subsystem of the Strata product, not a separate Strata project.

The current architecture is [Strata's C4 map](../docs/c4/map.yaml) and the [integration design](../docs/architect/endo-strata-merge.yaml). Agent governance, roles, workflow, and skills live in [the canonical `agent/` directory](../agent/). The Code map renderer lives in [`viewer/codemap/`](../viewer/codemap/), and GitNexus under [`tools/gitnexus/`](../tools/gitnexus/) is the repository scanner.

[`docs/c4/map.yaml`](docs/c4/map.yaml) is a historical snapshot of the earlier standalone Endo proposal. It includes a Tree-sitter Repo Map Engine design that was superseded by the Strata/GitNexus architecture. Do not import that map into the active Strata C4 project.
