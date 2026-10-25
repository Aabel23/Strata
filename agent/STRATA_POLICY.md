# Strata operation and role policy

Load `/home/abel/project/tools/strata/agent/skills/strata/SKILL.md` before the first Strata operation. That manual owns CLI/MCP syntax, schemas and server permissions. Use registered MCP when available; CLI is the main chat's fallback. Never edit the database with sqlite3. Test unfamiliar write operations against a temporary database using the manual's documented initialization and database override.

Strata at `/home/abel/project/tools/strata` stores workflow results; use implemented functionality. Register a missing project before stage 2. The main chat owns record/document writes and task approval/rejection/rework/done, with these narrow exceptions:
- Coders may claim/submit their ticket through their role MCP. CLI claim/submit is permitted only if the assigned role actually exposes that capability; otherwise return text to the main chat.
- Reviewers may propose issues through their role MCP, in `proposed` state for user approval; they cannot approve or change task state.
- Workers without role MCP return text for the main chat to record. These exceptions do not authorize other writes.

Strata holds design (C4, flows, docs), research and workflow records (tasks/issues); it is not used for repository scanning (`strata sym` is superseded for agent use); use GitNexus per [CODE_MAP.md](CODE_MAP.md).

C4 objects/flows follow the project's `docs/AGENT_C4.md`; validate cleanly before import. Link tickets/issues to corresponding C4 objects when available.

Requested documents default to Strata Docs, not the vault or Claude Docs. Research lives in `<docs_dir>/research/`; approved content-only YAML follows Strata's `docs/architect/doc-format.yaml` in project `architect/`, `plan/`, or `review/`. Do not build HTML/CSS/JS document renderers. Follow explicit user format/destination instructions within their scope. The main chat records research; researchers return text.

Legacy exception: `project1_app` keeps `documentation/plan/plan.json` until its current flow ends; new flows use Strata. RAM/OPEN remain in the vault; worker task context is not permission to read them.

Before designing Strata UI, load `artifact-design` or the user's selected design skill. If unavailable, report the missing prerequisite rather than claiming it ran.
