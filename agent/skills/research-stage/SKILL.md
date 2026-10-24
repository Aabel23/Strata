---
name: research-stage
description: Research design alternatives with repository evidence and primary-source citations, synthesize decisions, and prepare Strata research YAML. Use for design research, comparison requests, and deep research on an active topic; not implementation or automatic reverse engineering.
---

# Research stage

Research explains alternatives and open decisions; it does not approve a design or authorize source changes. Follow the owner's gated workflow and [Strata policy](../../STRATA_POLICY.md). Return English by default.

## Scope and dispatch

Resolve references such as “option 3” from available chat and repository evidence; the coordinator can consult private continuity through its startup rules, but must not forward vault content, conclusions or paths. If the reference remains ambiguous, ask rather than invent it. Explain blocks, responsibilities and data flow before unnecessary theory.

Explicit user choices of model, effort, number of agents and scope win. Otherwise, default research workers to Sonnet medium; use the restricted `researcher` profile where the host supports it. Deep research on an active topic authorizes dividing independent subquestions and dispatching them without asking the user to approve the split: default three, fewer than five unless requested. Include a cross-cutting integration question when relevant; do not create duplicate work. Announce who investigates what, then dispatch. Use background execution when supported.

Use [references/researcher-prompt.md](references/researcher-prompt.md) for a fresh, bounded worker prompt. Do not inherit the full conversation. Check actual capabilities before dispatch. A general-purpose fallback may expose broader tools; disclose that mismatch and retain the read-only task instruction without claiming isolation. A Codex host may expose different models; disclose actual mappings and respect explicit user model requests rather than silently replacing them.

Firecrawl is the preferred research provider when connected. Inspect available provider tools/status; if disconnected, tell the user that login may be needed (`claude mcp login firecrawl` or `/mcp` on Claude). Fall back to available web search/fetch and report why; do not claim unavailable tools ran.

## Evidence and synthesis

Require primary-source links and repository file:line evidence for material claims. Distinguish observations, vendor guidance, empirical results, inference and proposals. The coordinator verifies serious code findings before presenting them as confirmed. Summarize each worker's material findings in three to five points; agreement is not proof.

Synthesize the answer, proposed flow, tradeoffs, what to keep/change, unresolved user decisions with recommendations, and what can wait beyond MVP. Report discovered bugs with code references as not yet fixed. Include case studies only where they support a decision. Suggest existing features worth dissecting with source/type/reason, but do not run dissection automatically.

Only when the user requests dissection: default Opus low; shipped binaries/apps/firmware/live targets use `reverse-engineer-anything`, while open source repositories use source reading. Return mechanism, adaptation to our blocks/contracts and risks. Learn mechanisms, respect licensing, and do not copy protected code/assets. Explicit user profiles override defaults.

## Research document

The coordinator records results in `<docs_dir>/research/<specific-english-topic>.yaml` through Strata Docs. Before an operation, load the canonical Strata skill for exact commands; do not copy syntax here. Search existing research and indexed docs first, updating the matching topic rather than duplicating it.

Use Strata's `docs/architect/doc-format.yaml`: title, searchable one-sentence summary, code references and supported content blocks. Use question blocks with options/recommendations for decisions. Start with status **research** and state what is approved versus proposed; do not claim “nothing decided” when some requirements are binding. Explain the system/flow with a concrete example, component roles, evidence, open decisions, unsolved bugs, deferred work and sources. Make the document self-contained rather than relying on internal option labels.

Validate cleanly, scan/register and mark draft using the canonical manual. When the user approves the topic, produce the formal content in `<docs_dir>/architect/`; mark obsolete research outdated or retain current when still useful. Document replacement/deletion needs user authorization: inspect incoming references and tracked status, back up before deletion, and preserve uncertain files.

Handoff states the intended audience, document path and viewer link (`http://127.0.0.1:8740`, Docs), outcome, proposed additions requiring approval and unhandled findings. Saving unrelated session continuity still requires the session-saving request.
