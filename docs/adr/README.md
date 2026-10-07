# ADR Index

This directory stores Architecture Decision Records (ADRs) for behavior and
compatibility contracts in `llm_client`.

| # | Title | Status | Date | Applies to Plans |
|---|-------|--------|------|-----------------|
| 0001 | [Model identity v0](DECISIONS.md#0001-model-identity-v0) | Accepted | 2026-02-22 | Plan #3 |
| 0002 | [Routing config precedence](DECISIONS.md#0002-routing-config-precedence) | Accepted | 2026-02-22 | Plan #3 |
| 0003 | [Warning taxonomy](DECISIONS.md#0003-warning-taxonomy) | Accepted | 2026-02-22 | Plan #6 |
| 0004 | [Result model semantics migration](DECISIONS.md#0004-result-model-semantics-migration) | Accepted | 2026-02-23 | Plan #2 |
| 0005 | [Reason code registry governance](DECISIONS.md#0005-reason-code-registry-governance) | Accepted | 2026-02-23 | Plan #2 |
| 0006 | [Actor ID issuance policy](DECISIONS.md#0006-actor-id-issuance-policy) | Accepted | 2026-02-23 | Plan #2 |
| 0007 | [Observability contract boundary](DECISIONS.md#0007-observability-contract-boundary) | Accepted | 2026-02-23 | Plan #6 |
| 0008 | [Task graph evaluation contract boundary](../ARCHIVED_DOCS_INDEX.md) | Superseded 2026-03-24 | 2026-02-23 | Plan #6; `task_graph.py` extracted to project-meta and `experiment_eval.py` to `prompt_eval` (Plan #17); `llm_client/experiment_eval.py` remains as a compatibility shim |
| 0009 | [Long-thinking background polling](DECISIONS.md#0009-long-thinking-background-polling) | Accepted | 2026-02-23 | Plan #7 |
| 0010 | [Cross-project runtime substrate](DECISIONS.md#0010-cross-project-runtime-substrate) | Accepted | 2026-03-17 | Plan #10 |
| 0011 | [Prompt assets explicit identity](DECISIONS.md#0011-prompt-assets-explicit-identity) | Accepted | 2026-03-17 | Plans #11–#12 |
| 0012 | [Shared data plane boundary](DECISIONS.md#0012-shared-data-plane-boundary) | Accepted | 2026-03-17 | Plan #12 |
| 0013 | [Stream lifecycle heartbeat observability](DECISIONS.md#0013-stream-lifecycle-heartbeat-observability) | Accepted | 2026-03-22 | Plan #7 |
| 0014 | [Call replay and divergence diagnosis boundary](DECISIONS.md#0014-call-replay-and-divergence-diagnosis-boundary) | Accepted | 2026-03-22 | Plan #9 |
| 0015 | [Provider governance and shared coordination](0015-provider-governance-and-shared-coordination.md) | Accepted | 2026-04-05 | Plan #25 |
| 0015 (duplicate number) | [Present LLM Client as runtime substrate evidence](DECISIONS.md#0015-portfolio-runtime-substrate-scope) | Accepted | undated (added 2026-06-23 per git history) | Portfolio presentation scope |
| 0016 | [Provider capability and vendor telemetry boundary](DECISIONS.md#0016-provider-capability-and-vendor-telemetry-boundary) | Accepted | 2026-07-22 | Plan #110 |

Number 0015 is used by two ADRs (provider governance, dated 2026-04-05, and
portfolio runtime-substrate scope, added 2026-06-23). The files are kept under
their existing names because other documents link to them; the next ADR is 0017.

Related architecture docs:

- `../ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md`
- `project-meta/docs/ops/ADR-2026-04-04-workflow-portability-revised-execution-strategies.md` — Plan #24 is Cancelled and redirected to this decision (external to this repository; not verifiable here)

Status: active.

Wiki route: [wiki/index.md](../../wiki/index.md) is the repository front door.
