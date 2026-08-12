# Implementation Plans

Track all implementation work here.

## Agent collaboration stack (Plans #29-35)

The implementer/reviewer duet shipped across four plans plus six followup
commits, with each plan dogfooded against the prior one's outputs (the
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

Plan #37 is the long-running execution spine for Plan #36. Use it as the
tracker when running continuously: it defines stop conditions, phase gates,
adversarial-review checkpoints, test commands, and completion criteria.

## Current Execution

- **Canonical main:** `5a3369e` (verified 2026-07-25; 1,948 passed, 3 skipped,
  12 deselected).
- **Merged, awaiting downstream acceptance:** Plans #121, #122, #124, and
  #334. Plan #124's shared implementation is verified locally; its remaining
  acceptance is one governed Process Tracing replay.
- **Other open work:** Plan #91's shared controller-churn implementation is
  landed and awaits one governed DIGIMON replay. Plan #94's technical output
  ceiling remains an implementation gap. Neither silently blocks Plan #124.
- **Blocked:** Plan #35 optional Phase 6 requires a fresh user decision.

## Gap Summary

| # | Name | Priority | Status | Blocks |
|---|------|----------|--------|--------|
| 350 | [Cross-Project Model Experiment Records](350_cross_project_model_experiment_records.md) | High | ✅ Complete | Reusable evidence-based model routing across projects |
| 349 | [Structured Recovery and Provider Exclusion](349_structured_recovery_and_provider_exclusion.md) | Critical | ✅ Complete | - |
| 348 | [GPT-5.4 Ban and Luna Default](348_gpt54_ban_luna_default.md) | Critical | ✅ Complete | consistent ecosystem model selection |
| 347 | [OpenRouter Response Cache Controls](347_openrouter_response_cache_controls.md) | Critical | ✅ Complete | cost-bounded Inside Success corpus preprocessing |
| 346 | [Production LLM Call Receipt](346_production_llm_call_receipt.md) | Critical | 🚧 In Progress | Team-Brains Hermes observability adapter |
| 345 | [Metadata-Only Call Observability](345_metadata_only_call_observability.md) | Critical | ✅ Complete | Qualitative Coding public guest-analysis privacy repair |
| 344 | [Codex GPT-5.6 Terra Subscription Route](344_codex_terra_subscription_route.md) | High | ✅ Complete | Cybernetic Influence Packet 21B2 pressure/stabilization canaries |
| 339 | [Structured Route Capability and Disconnect Retry](339_structured_route_capability_and_disconnect_retry.md) | Critical | 🚧 In Progress | Process Tracing Plan 020 terminal repair replay |
| 340 | [Codex GPT-5.6 Luna Subscription Route](340_codex_luna_subscription_route.md) | High | ✅ Complete | Cybernetic Influence subscription-backed live simulation |
| 343 | [Codex Certification Integrity](343_codex_certification_integrity.md) | Critical | ✅ Complete | Trustworthy downstream route advertisement |
| 336 | [Typed OpenRouter Route Policy and Consumer Migration](336_typed_openrouter_route_policy.md) | Critical | 🚧 In Progress | Inside Success DP-03 real messy-Slack preprocessing vertical |
| 124 | [Logical Structured-Call Deadline](124_logical_structured_call_deadline.md) | Critical | ❓  | Bounded retry-chain latency and Plan 021 terminal repair |
| 121 | [Privacy-Bounded Attempt Diagnostic Envelope](121_attempt_diagnostic_envelope.md) | Critical | ❓  | Evidence-based failure localization and provider-attribution claims |
| 120 | [Durable Cross-Project Call Lifecycle](120_durable_call_lifecycle.md) | Critical | ✅ Complete | Truthful localization of missing-terminal calls |
| 119 | [Runtime Cost Governance](119_runtime_cost_governance.md) | Critical | ✅ Complete | Trustworthy real-time cost control and cross-provider spend analysis |
| 118 | [OpenRouter Discriminated-Union Projection](118_openrouter_schema_compaction.md) | High | ✅ Complete | DoDAF Plan 75 Army publication extraction |
| 117 | [Explicit Reasoning Policy](117_explicit_reasoning_policy.md) | Critical | ✅ Complete | Cost- and latency-controlled reasoning-model execution |
| 116 | [Ecosystem Allowlist Cutover](116_ecosystem-allowlist-cutover.md) | Critical | ✅ Complete | Unconditional allowed-model enforcement |
| 115 | [Allowed-Model Execution Policy](115_allowed-model-execution-policy.md) | Critical | ✅ Complete | Safe cross-project model-policy enforcement |
| 114 | [JSON-Schema-Native Bridge](114_json-schema-native-bridge.md) | High | ✅ Complete | learning-environment migration away from direct provider transport |
| 113 | [Responses Structured Custody Reconciliation](113_responses_structured_custody_reconciliation.md) | Critical | ❓  | onto-canon6 Plan 0145 reviewed preprocessing replay |
| 112 | [Provider Usage-Detail Observability](112_provider_usage_detail_observability.md) | High | ✅ Complete | Exact hidden-reasoning attribution in downstream cost experiments |
| 111 | [All-Attempt Structured Cost Coverage](111_all_attempt_cost_coverage.md) | Critical | ✅ Complete | Honest recovered structured calls in strict-budget consumers |
| 108 | [Agent-schema Responses compatibility](108_agent_schema_responses_compatibility.md) | High | ✅ Complete | Cybernetic simulator exact-schema route certification |
| 107 | [Direct GPT-5.6 Route Registration](107_gpt56_direct_route_registration.md) | High | ✅ Complete | Direct GPT-5.6 Sol and Terra strict-schema routes explicitly selectable; no automatic tier-default change |
| 106 | [Direct GPT-5.5 Structured Capability Truth](106_gpt55_structured_capability_truth.md) | High | ❓  | Its alleged direct result was an OpenRouter-proxy route; corrected by Plan 107 |
| 105 | [Personal and Inside Success Fork Reconciliation](105_inside_success_fork_reconciliation.md) | High | ✅ Complete | A single current `llm_client` line for personal and Inside Success consumers |
| 102 | [Exact selected raw structured content](102_selected_raw_structured_content.md) | High | ✅ Complete | onto-canon6 Plan 0141 transport-receipt construction |
| 100 | [Budget-complete call snapshot v3](100_budget_complete_call_snapshot_v3.md) | High | ✅ Complete | DoDAF fresh page-window diagnostic |
| 101 | [Runtime-selected structured attempt receipt](101_runtime_selected_attempt_receipt.md) | High | ✅ Complete | onto-canon6 Plan 0141 trusted-runner receipt pinning |
| 103 | [Codex CLI Approval Compatibility](103_codex_cli_approval_compatibility.md) | High | ✅ Complete | ecosystem-ops direct Codex dispatch certification |
| 104 | [OpenRouter Provider-Limit Observer](104_openrouter-provider-limit-observer.md) | Critical | ✅ Complete | onto-canon6 Plan 0141 and Greer governed-mapping stress test |
| 1 | [LLM Client Master Roadmap](01_master-roadmap.md) | Highest | ❓  | - |
| 2 | [Client Boundary Hardening Program](02_client-boundary-hardening.md) | High | ✅ Complete | - |
| 3 | [Model Policy Modernization](03_model-policy-modernization.md) | High | ✅ Complete | - |
| 4 | [Workflow Layer Boundary](04_workflow-layer-boundary.md) | Medium | ✅ Complete | - |
| 5 | [Eval Boundary Cleanup](05_eval-boundary-cleanup.md) | Medium | ✅ Complete | - |
| 6 | [Simplification & Observability](06_simplification-and-observability.md) | High | ✅ Complete | - |
| 7 | [Stream Lifecycle Heartbeat and Stagnation Visibility](07_stream_lifecycle_observability.md) | High | ✅ Complete | - |
| 8 | [llm_client Subtree Instruction Rollout](08_llm_client-subtree-instructions.md) | Medium | ✅ Complete | - |
| 9 | [Replay and Divergence Diagnosis](09_replay-and-divergence-diagnosis.md) | High | ✅ Complete | - |
| 10 | [API Reference Generation Pipeline](10_api-reference-generation-pipeline.md) | High | ✅ Complete | - |
| 11 | [Program E Module Size Reduction](11_program-e-module-size-reduction.md) | High | ✅ Complete | 6 |
| 12 | [Module Reorganization (Flat → Layered)](12_module-reorganization.md) | High | ✅ Complete | 11 |
| 13 | [SDK Adapter Simplification](13_sdk-adapter-simplification.md) | Medium | ✅ Complete | 12 |
| 14 | [Batch Progress & Stagnation Detection](14_batch-progress-and-stagnation.md) | High | ✅ Complete | - |
| 15 | [Centralize Hardcoded Defaults into ClientConfig](15_centralize-defaults.md) | Low | ❓  | - |
| 16 | [Remove Compatibility Stubs](16_remove-compatibility-stubs.md) | Medium | ✅ Complete | 12 |
| 17 | [text_runtime Sync/Async Deduplication](17_text-runtime-dedup.md) | High | ✅ Complete | - |
| 18 | [Agent Loop Error Budget and Retry Policy](18_agent_loop_error_budget.md) | High | ✅ Complete | - |
| 19 | [Agent Planning and Working Memory](19_agent_planning_and_working_memory.md) | High | ✅ Complete | - |
| 20 | [Makefile and Requirements](20_makefile_and_requirements.md) | Medium | ✅ Complete | - |
| 21 | [Runtime Durability Follow-Ups From Grounded Research](21_runtime_durability_followups_from_grounded_research.md) | High | ✅ Complete | - |
| 22 | [Capability Ownership And Sanctioned Worktree Alignment](22_capability-ownership-and-sanctioned-worktree-alignment.md) | High | ✅ Complete | 21 |
| 23 | [Authoritative coordination wave-1 rollout](23_authoritative-coordination-wave-1-rollout.md) | Critical | ✅ Complete | - |
| 24 | [Workflow Kit Manifest, Validator, and Runtime Adapter Proving Slice](24_workflow-kit-manifest-validator-and-runtime-adapter-proving-slice.md) | — | ❓  | — |
| 25 | [Gemini Exhaustion Fallback Hardening](25_gemini_exhaustion_fallback_hardening.md) | High | ✅ Complete | - |
| 26 | [Gemini Strict-Schema Behavior Study](26_gemini-strict-schema-behavior-study.md) | High | ✅ Complete | - |
| 27 | [Direct Gemini Thinking Budget Policy](27_direct-gemini-thinking-budget-policy.md) | High | ✅ Complete | 26 |
| 28 | [OpenRouter Gemini 3.1 Pro Registry And Tyler Validation](28_openrouter-gemini31-pro-registry-and-tyler-validation.md) | High | ✅ Complete | 26, 27 |
| 29 | [Implementer/Reviewer Duet Workflow](29_implementer_reviewer_duet.md) | Medium | ✅ Complete | - |
| 30 | [Duet Autonomous Hardening](30_duet_autonomous_hardening.md) | High | ✅ Complete | 29 |
| 31 | [TaskFamily Abstraction for the Duet Chassis](31_task_family_abstraction.md) | High | ✅ Complete | 30 |
| 32 | [twin_update Profile](32_twin_update_profile.md) | High | ✅ Complete | 31 |
| 33 | [Deliberation Workflow (Symmetric N-Agent Debate)](33_deliberation_workflow.md) | High | ✅ Complete | 31 |
| 34 | [Deliberation Verifier / Adjudicator Stage](34_deliberation_verifier_adjudicator.md) | High | ✅ Complete | 33 |
| 35 | [Within-Round Barrier Protocol + Anonymization](35_deliberation_within_round_barrier_protocol.md) | High | ⏸️ Blocked (optional Phase 6 requires decision) | 34 |
| 36 | [Intermodel Review Consolidation and Whitepaper Loop](36_intermodel_review_consolidation.md) | Critical | ✅ Complete (private-only accepted) | Existing repo stays private unless reopened for public release |
| 37 | [Long-Running Execution Spine for Intermodel Review](37_long_running_intermodel_review_execution.md) | Critical | ✅ Complete (private-only accepted) | 36 |
| 38 | [Exhausted-Model Cooldown Routing](38_exhausted_model_cooldown_routing.md) | High | ✅ Complete | - |
| 39 | [Long Retry-Hint Failover](39_long_retry_hint_failover.md) | High | ✅ Complete | 38 |
| 40 | [Provider Governance and Shared Coordination](40_provider-governance-and-shared-coordination.md) | Critical | ❓  | 94, 104, 115-122, 333-335 |
| 41 | [Embedding Budget Contract](41_embedding_budget_contract.md) | High | ✅ Complete | onto-canon6 Plan 0162 live semantic candidate retrieval |
| 42 | [Codex CLI MCP Parity](42_codex_cli_mcp_parity.md) | High | ✅ Complete | Inside Success Twitter prospecting agent |
| 43 | [Version Adversarial Review Prompts as Assets](43_review_prompt_assets.md) | Medium | ✅ Complete | - |
| 44 | [Reconcile Completed Cross-Project Plan Status](44_plan_status_reconciliation.md) | Medium | ✅ Complete | - |
| 91 | [Pending-Atom Submit Churn Requires TODO Progress](91_pending_atom_submit_churn_requires_todo_progress.md) | High | ❓  | DIGIMON governed replay |
| 93 | [Agent tool-usage ledger](93_agent-tool-usage-ledger.md) | High | ✅ Complete | project-meta Plan #213 reporting and comparative selection evaluation |
| 92 | [Worktree Lifecycle Governance and Cleanup](92_worktree-lifecycle-governance-and-cleanup.md) | Critical | ✅ Complete | Merge-or-disposition enforcement live; historical checkout cleanup reconciled |
| 94 | [Model Tier Taxonomy and Fable Ban](94_model-tier-taxonomy-and-fable-ban.md) | High | 🚧 In Progress (tier selectors implemented; declared-vs-certified route follow-up open) | Cross-project model-selection cleanup |
| 95 | [Require llm_client Registration Audit](95_require-llm-client-registration-audit.md) | High | ✅ Complete | Cross-project enforcement of shared LLM routing |
| 96 | [Registration-Only Audit Fast Path](96_registration-only-audit-fastpath.md) | High | ✅ Complete | Cross-project llm_client registration classification |
| 97 | [Lossless structured-output attempt observability](97_lossless-structured-output-attempt-observability.md) | High | ✅ Complete | DIGIMON Plan #110 ledger-bound trace verification |
| 98 | [Async structured-attempt liveness](98_async_structured_attempt_liveness.md) | High | ✅ Complete | DIGIMON Plan #111 bound-trace refresh |
| 99 | [Strict native JSON-schema execution](99_strict_native_json_schema_execution.md) | High | ✅ Complete | onto-canon6 Plan 0141 exact dependency binding |
| 109 | [Structured-Call Hard Deadline](109_structured_call_hard_deadline.md) | High | ✅ Complete | Reliable long-running structured simulations |
| 110 | [Provider Capabilities and Opus Ban](110_provider-capabilities-opus-ban.md) | High | ✅ Complete | Cybernetic simulator DeepSeek V4 Flash max-reasoning sample |
| 333 | [root budget scope across child traces](333_root-budget-scope-across-child-traces.md) | High | ✅ Complete | Plan #335 concurrent root-budget reservations |
| 122 | [Client Attempt Deadline Classification](122_client-attempt-deadline-classification.md) | High | ❓  | Plan #121 merged diagnostics contract |
| 334 | [Empty Structured Response Observability](334_empty-structured-response-observability.md) | Critical | ❓  | Plan #122 client deadline classification |
| 335 | [Concurrent Root-Budget Reservations](335_concurrent-root-budget-reservations.md) | Critical | ✅ Complete | DIGIMON Plan #182 |
| 337 | [Current Model Selection Evidence and GPT-5.5 Retirement](337_current-model-selection-evidence-and-gpt-5-5-retirement.md) | Critical | ✅ Complete | - |
| 338 | [Observed Application-Run Lifecycle](338_observed_application_run_lifecycle.md) | Critical | ❓  | Process Tracing outer-run receipt |


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
