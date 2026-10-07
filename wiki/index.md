---
id: inside-success-llm-client-wiki-index
type: index
title: "Inside Success LLM Client wiki front door"
status: authored
authority: derived
owner: Inside-Success/llm_client
as_of: 2026-10-07
visibility: unknown
source_of_truth: false
---

# Inside Success LLM Client

Front door for `Inside-Success/llm_client`. Orientation only: every claim here is routed to the native file that owns it, and that file wins when they differ. Read this page before searching the repository.

## What this repository is

A unified LLM client with mandatory observability, cost tracking and policy enforcement, built on LiteLLM ([README](../README.md)). The project dossier is `PROJECT.md`. The repo is independent and canonical for Inside Success since 2026-10-03; `BrianMills2718/llm_client` is the former personal upstream, kept as ancestry only: do not sync, merge or port from it ([AGENTS.md](../AGENTS.md), "Repository Identity").

## Where live docs are

- Operating rules: [AGENTS.md](../AGENTS.md)
- What `llm_client` owns versus consumes from other repos: `docs/ops/CAPABILITY_DECOMPOSITION.md`
- Plans and delivery status (the status owner): [plan index](../docs/plans/AGENTS.md)
- Architecture decisions: [ADR index](../docs/adr/README.md)
- Architecture orientation (source-bound codebase wiki) and the plans/codebase navigation split: [roadmap](../roadmap/README.md)
- Documentation directory front door: [docs/README.md](../docs/README.md) (routes to every doc, guide and subtree rule file)
- Open issues: `ISSUES.md`; shared agent findings: `KNOWLEDGE.md`; changes: `CHANGELOG.md`

## Consolidated record files

Groups of small records are kept as one file each; every former file is a section whose anchor is its old file name without `.md` (old path to anchor table: [archived docs index](../docs/ARCHIVED_DOCS_INDEX.md#consolidated-not-removed-2026-10-07)).

- Architecture decisions: [docs/adr/DECISIONS.md](../docs/adr/DECISIONS.md) holds ADRs 0001-0007, 0009-0014, 0015 (portfolio scope) and 0016, e.g. [ADR 0001 model identity](../docs/adr/DECISIONS.md#0001-model-identity-v0), [ADR 0010 runtime substrate](../docs/adr/DECISIONS.md#0010-cross-project-runtime-substrate), [ADR 0016 provider capability](../docs/adr/DECISIONS.md#0016-provider-capability-and-vendor-telemetry-boundary). ADR 0015 (provider governance) stays its own file; the [ADR index](../docs/adr/README.md) lists all of them with status.
- Completed plans: [docs/plans/COMPLETED_PLANS.md](../docs/plans/COMPLETED_PLANS.md) holds Plans [#33](../docs/plans/COMPLETED_PLANS.md#33_deliberation_workflow), [#34](../docs/plans/COMPLETED_PLANS.md#34_deliberation_verifier_adjudicator), [#99](../docs/plans/COMPLETED_PLANS.md#99_strict_native_json_schema_execution), [#104](../docs/plans/COMPLETED_PLANS.md#104_openrouter-provider-limit-observer), [#110](../docs/plans/COMPLETED_PLANS.md#110_provider-capabilities-opus-ban), [#117](../docs/plans/COMPLETED_PLANS.md#117_explicit_reasoning_policy) and [#348](../docs/plans/COMPLETED_PLANS.md#348_gpt54_ban_luna_default). Active, implemented-pending-acceptance and blocked plans stay as `docs/plans/NN_name.md` files because the plan tooling reads them per file; completed Plans #22 and #105 stay as files because hash-pinned codebase-wiki sources reference them.
- Run and operational evidence: [docs/runs/RUNS.md](../docs/runs/RUNS.md) holds the [2026-07-09 worktree disposition report](../docs/runs/RUNS.md#2026-07-09-worktree-disposition-report), the [2026-07-21 GPT-5.6 planner-schema compatibility run](../docs/runs/RUNS.md#2026-07-21_openrouter_gpt56_planner_schema_compatibility), the [2026-07-25 Sol authoring-schema certification](../docs/runs/RUNS.md#2026-07-25_openrouter_gpt56_sol_authoring_schema_certification) and the [2026-07-27 typed route-policy probe](../docs/runs/RUNS.md#2026-07-27_typed_openrouter_route_policy_probe).

## Superseded or point-in-time

- Finished plans, dated reviews, investigations and handoffs removed on 2026-10-07 (including `docs/HANDOFF.md` and superseded ADR 0008) are listed, with restore commands, in the [archived docs index](../docs/ARCHIVED_DOCS_INDEX.md).
- [.claude/HANDOFF.md](../.claude/HANDOFF.md) is a point-in-time session handoff; the plan index wins on status.
- Do not treat the codebase wiki as proof of an exact signature; reopen the native source ([AGENTS.md](../AGENTS.md), rule 9).

## Code and how to run

- Implementation lives in the Python package [llm_client/](../llm_client/); [src/](../src/) holds only a routing README to it. Tests: [tests/](../tests/).
- Install, test and check commands are targets in the [Makefile](../Makefile): `make install` (editable install with dev extras), `make test`, `make lint`, `make typecheck`, `make codebase-wiki-check`, and `make check` (all of these). Packaging: [pyproject.toml](../pyproject.toml). Usage examples: [README](../README.md).

## Coverage and limits

- This page is hand-authored from the repository's own files on 2026-10-03 (consolidated-record routes added 2026-10-07); it is not a reviewed enrichment pass and does not summarise the plan files.
- `make codebase-wiki-check` passes on `main` as of 2026-10-03 after the wiki was re-derived from `Inside-Success/llm_client` revision `fe581ed` (manifest `roadmap/codebase/raw/source-manifest-fe581ed-inside-success.json`), including its concept and workflow pages; see the source ingest page under [roadmap](../roadmap/README.md). Owner of the next gap: this repository's maintainers, tracked through the [plan index](../docs/plans/AGENTS.md).

## If this page did not answer your question

Find the answer, then **add the route here before you finish the work that made you look**. A wiki that is only ever read decays; this is the only mechanism by which it improves, and the gap is cheapest to close while you still have the answer in front of you.

- Add **where the answer lives**, not an essay.
- If what you found contradicts this page, fix it or mark it stale; leaving both is worse than either.
- If the answer belongs to a native authority, link that authority rather than copying its content here.
