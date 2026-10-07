# Implementation Plans

Track all implementation work here.

## Agent collaboration stack (Plans #29-35)

The implementer/reviewer duet shipped across four plans, with each plan dogfooded against the prior one's outputs (the
artifacts live in `runs/`):

- **Plan #29** — chassis: LangGraph stages, schemas, routers, persistence.
- **Plan #30** — hardening: cwd threading, grounded schemas, `duet-review` CLI.
- **Plan #31** — `TaskFamily` abstraction: chassis split from profiles; `generic` + `plan_doc_review` profiles.
- **Plan #32** — `twin_update` profile: PCM v2 layers + Twin Fidelity rubric axes + proof authority contract.

Entry point for callers: `python -m llm_client duet-review --help`.
Module docstring at `llm_client/workflow/duet.py` summarizes the full
architecture and points to each plan's design rationale.

The sibling deliberation stack is now implemented through Plans #33-35:

- **Plan #33** — symmetric two-agent debate via `python -m llm_client deliberate-task`.
- **Plan #34** — verifier/adjudicator ledger for claim evidence and lineage.
- **Plan #35** — within-round barrier protocol and peer anonymization, with
  tracked dogfood evidence in `runs/plan-35-barrier-pilot/`.

Start with `docs/guides/agent-collaboration.md` when packaging or demoing the
Claude/Codex collaboration surfaces.

Plan #36 is the consolidation layer on top of those primitives: canonical
standalone review profiles, the `quality_optimal_whitepaper` review profile,
the synchronous `review-cycle` runner, OpenClaw scheduling boundaries, and
legacy dialogue-code archival.

Plan #37 was the long-running execution spine for Plan #36 (stop conditions,
phase gates, adversarial-review checkpoints, test commands, completion
criteria). Both plans are Complete (private-only accepted).

## Current Execution

- **Implemented, awaiting downstream acceptance:** Plan #364 binds Codex lifecycle failures to an opaque
  executing-account digest so multi-account consumers cannot confuse one
  profile's usage limit with global Luna capacity.
- **Completed documentation vertical:** Plan #358 compiles the revision-bound
  `llm_client` capsule and exact source into a Karpathy-style codebase wiki and
  proves wiki-first navigation back to native source.
- **Completed wiki maintenance vertical:** Plan #359 enforces source freshness
  and ingests the separately owned Inside Success downstream capsule.
- **Implemented provider-free:** Plan #363 adds explicit exact-session Codex CLI
  resume/fork controls; AC16 downstream adoption remains open.
- **Canonical main:** current `main` (verify its revision at integration time).
- **Implemented, awaiting downstream acceptance (other):** Plans #355 (Agent
  Ecology 3 preflight and AC16 pin), #346 (Team-Brains Hermes adapter), #338
  (Process Tracing non-mocked receipt), #339 (shared-client publication and
  Process Tracing replay), and #336 (shared client landed; Inside Success
  consumer migration open).
- **Focused verification only:** Plan #361 (workload route selection) and
  Plan #113 (focused verified; repository completion gate unavailable). Plan
  #360 is superseded in part by #361: `DEFAULT_EXECUTION_MODEL` is again
  `openrouter/openai/gpt-5.6-luna`, a compatibility fallback.
- **Merged, awaiting downstream acceptance:** Plans #121, #122, #124, and
  #334. Plan #124's shared implementation is verified locally; its remaining
  acceptance is one governed Process Tracing replay.
- **Other open work:** Plan #91's shared controller-churn implementation is
  landed and awaits one governed DIGIMON replay. Plan #94's task-configured
  technical output ceiling remains an implementation gap. Neither silently blocks Plan #124.
- **Blocked:** Plan #35 optional Phase 6 requires a fresh user decision.

## Gap Summary

| # | Name | Priority | Status | Blocks |
|---|------|----------|--------|--------|
| 364 | [Codex Account Identity Receipts](364_codex_account_identity_receipts.md) | Critical | 🚧 Implemented (WhyGame acceptance pending) | deterministic multi-account Codex consumers |
| 363 | [Codex CLI Session Continuation](363_codex_session_continuation.md) | High | 🚧 Implemented (provider-free; downstream adoption pending) | AC16 Plan #02 exact-session healing harness |
| 361 | [Compatibility-Aware Workload Route Selection](361_workload_route_selection.md) | High | 🚧 Implemented (focused verification) | explicit Codex/API/OpenRouter provider selection |
| 355 | [Codex Intrinsic Event Custody](355_codex_intrinsic_event_custody.md) | High | 🚧 Implemented (downstream Agent Ecology 3 / AC16 acceptance pending) | AC16 Plan 02 and Agent Ecology 3 Plan #10 |
| 348 | [GPT-5.4 Ban and Luna Default](COMPLETED_PLANS.md#348_gpt54_ban_luna_default) | Critical | ✅ Complete | consistent ecosystem model selection |
| 346 | [Production LLM Call Receipt](346_production_llm_call_receipt.md) | Critical | 🚧 Implemented (Team-Brains Hermes adapter acceptance pending) | Team-Brains Hermes observability adapter |
| 339 | [Structured Route Capability and Disconnect Retry](339_structured_route_capability_and_disconnect_retry.md) | Critical | 🚧 In Progress | Process Tracing Plan 020 terminal repair replay |
| 336 | [Typed OpenRouter Route Policy and Consumer Migration](336_typed_openrouter_route_policy.md) | Critical | 🚧 In Progress (shared client landed; consumer migration open) | Inside Success DP-03 real messy-Slack preprocessing vertical |
| 124 | [Logical Structured-Call Deadline](124_logical_structured_call_deadline.md) | Critical | 🚧 Implemented; downstream verification pending | Bounded retry-chain latency and Plan 021 terminal repair |
| 121 | [Privacy-Bounded Attempt Diagnostic Envelope](121_attempt_diagnostic_envelope.md) | Critical | 🚧 Implemented on main; downstream Process Tracing verification pending | Evidence-based failure localization and provider-attribution claims |
| 117 | [Explicit Reasoning Policy](COMPLETED_PLANS.md#117_explicit_reasoning_policy) | Critical | ✅ Complete | Cost- and latency-controlled reasoning-model execution |
| 113 | [Responses Structured Custody Reconciliation](113_responses_structured_custody_reconciliation.md) | Critical | 🚧 Implemented (focused verified; repository completion gate unavailable) | onto-canon6 Plan 0145 reviewed preprocessing replay |
| 105 | [Personal and Inside Success Fork Reconciliation](105_inside_success_fork_reconciliation.md) | High | ✅ Complete | A single current `llm_client` line for personal and Inside Success consumers |
| 104 | [OpenRouter Provider-Limit Observer](COMPLETED_PLANS.md#104_openrouter-provider-limit-observer) | Critical | ✅ Complete | onto-canon6 Plan 0141 and Greer governed-mapping stress test |
| 1 | [LLM Client Master Roadmap](01_master-roadmap.md) | Highest | Active authority | - |
| 22 | [Capability Ownership And Sanctioned Worktree Alignment](22_capability-ownership-and-sanctioned-worktree-alignment.md) | High | ✅ Complete | 21 |
| 33 | [Deliberation Workflow (Symmetric N-Agent Debate)](COMPLETED_PLANS.md#33_deliberation_workflow) | High | ✅ Complete | 31 |
| 34 | [Deliberation Verifier / Adjudicator Stage](COMPLETED_PLANS.md#34_deliberation_verifier_adjudicator) | High | ✅ Complete | 33 |
| 35 | [Within-Round Barrier Protocol + Anonymization](35_deliberation_within_round_barrier_protocol.md) | High | ⏸️ Blocked (optional Phase 6 requires decision) | 34 |
| 91 | [Pending-Atom Submit Churn Requires TODO Progress](91_pending_atom_submit_churn_requires_todo_progress.md) | High | 🚧 Implemented; downstream verification pending | DIGIMON governed replay |
| 94 | [Model Tier Taxonomy and Fable Ban](94_model-tier-taxonomy-and-fable-ban.md) | High | 🚧 In Progress (tier selectors and route-certification emission implemented; technical output ceiling not implemented) | Cross-project model-selection cleanup |
| 99 | [Strict native JSON-schema execution](COMPLETED_PLANS.md#99_strict_native_json_schema_execution) | High | ✅ Complete | onto-canon6 Plan 0141 exact dependency binding |
| 110 | [Provider Capabilities and Opus Ban](COMPLETED_PLANS.md#110_provider-capabilities-opus-ban) | High | ✅ Complete | Cybernetic simulator DeepSeek V4 Flash max-reasoning sample |
| 122 | [Client Attempt Deadline Classification](122_client-attempt-deadline-classification.md) | High | 🚧 Implemented on main; downstream Process Tracing verification pending | Plan #121 merged diagnostics contract |
| 334 | [Empty Structured Response Observability](334_empty-structured-response-observability.md) | Critical | 🚧 Implemented on main; governed downstream live trace pending | Plan #122 client deadline classification |
| 338 | [Observed Application-Run Lifecycle](338_observed_application_run_lifecycle.md) | Critical | 🚧 Implemented; legacy-schema repair verified, downstream rerun pending | Process Tracing outer-run receipt |


Finished plans (81 rows: Complete, Cancelled or Superseded) were removed
from this table and the tree on 2026-10-07. Their titles and restore commands
are in [ARCHIVED_DOCS_INDEX.md](../ARCHIVED_DOCS_INDEX.md).

## Status Key

| Status | Meaning |
|--------|---------|
| Planned | Ready to implement |
| In Progress | Being worked on |
| Blocked | Waiting on dependency |
| Implemented | Canonical code landed; named downstream acceptance remains |
| Complete | Implemented and verified |
| Superseded | Replaced by named plans or decisions; not active |
| Cancelled | Explicitly rejected; no planned work |

## Creating a New Plan

1. Copy `TEMPLATE.md` to `NN_name.md`
2. Fill in gap, steps, required tests
3. Add to this index
4. Commit with `[Plan #N]` prefix

## Trivial Changes

Not everything needs a plan. Use `[Trivial]` for:
- Less than 20 lines changed
- No changes to `llm_client/` (production code)
- No new files created

```bash
git commit -m "[Trivial] Fix typo in README"
```

## Completing Plans

```bash
python scripts/meta/complete_plan.py --plan N
```

This verifies tests pass and records completion evidence.

Wiki route: [wiki/index.md](../../wiki/index.md) is the repository front door.
