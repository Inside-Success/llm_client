# Plan #111: All-Attempt Structured Cost Coverage

**Status:** Complete (2026-07-22)
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Honest recovered structured calls in strict-budget consumers

---

## Frame

Make one logical structured call report the cost of every provider response
that contributed to its terminal result, including schema-invalid responses
repaired by the retry kernel. Preserve uncertainty when a started attempt has
no priceable response.

## Gap

**Current:** The native structured runtime retains every attempt's lifecycle
and raw response lineage, but the returned `LLMCallResult.cost` describes only
the selected terminal response. A live DeepSeek call produced a billed,
schema-invalid response and then a valid repair response; the consumer
correctly refused to treat the selected-response price as aggregate spend.

**Target:** Native structured sync and async results aggregate every observed
attempt price into the logical-call `cost`/`marginal_cost` and expose whether
that aggregate covers every started attempt. A timeout, pre-return provider
validation exception, or other unpriceable attempt keeps coverage explicitly
false or unknown.

**Why:** Retry is owned by this runtime substrate. Downstream callers cannot
reconstruct hidden attempt billing safely, and must not choose between
discarding a valid recovery and silently undercounting spend.

## References Reviewed

- `CLAUDE.md` and package/execution/core/test subtree instructions.
- `docs/adr/0007-observability-contract-boundary.md` — local execution evidence.
- `docs/adr/0010-cross-project-runtime-substrate.md` — shared retry ownership.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — logical
  call and attempt identity.
- Plans 97, 101, and 109 — lossless attempts, selected receipts, and deadlines.
- `llm_client/core/data_types.py`, `llm_client/schemas.py`,
  `llm_client/execution/structured_runtime.py`, and
  `llm_client/utils/cost_utils.py`.
- Cybernetic live job `dj_c9014c076b80425e` — provider-accepted invalid
  `memory_update`, successful repair, and honest aggregate-cost refusal.

## Modality Diagnosis

Deductive. A logical call's started attempts, priceable returned responses,
aggregate arithmetic, and coverage status are exact runtime facts. Whether a
recovered model response is behaviorally useful belongs to the consuming
experiment and is not judged here.

## Semantic Boundary

This slice fixes native structured calls because that is the deployed path
with complete per-attempt response ownership. It does not build a billing
system, infer provider charges after timeouts, parse vendor dashboards, or
claim coverage for Instructor/agent/other paths whose internal attempts are
not fully visible.

## Risk-Ordered Slices

### Slice 1 — Aggregate provider-accepted native structured responses

Add failing sync/async tests, one internal attempt-cost ledger, and an additive
coverage field on the result/schema. Compute a response's price before local
Pydantic validation so a repairable invalid response is not lost. Apply the
ledger exactly once to the terminal logical result and observability row.

**Done when:** two priceable attempts return their sum with coverage true,
single-attempt behavior remains unchanged, and a timeout-plus-success negative
returns only known spend with coverage false.

### Slice 2 — Audit adjacent retry and cache boundaries

Attack fallback, provider pre-return validation, finalization failure, cache
hit, sync/async parity, and selected-attempt identity. Keep unsupported paths
unknown rather than manufacturing completeness. Regenerate public API
reference if required and triage the concern register.

**Done when:** focused gates pass, changed surfaces are lint/type clean, no
duplicate cost is logged, and every audit finding is resolved or registered.

## Files Affected

- `llm_client/core/data_types.py`
- `llm_client/schemas.py`
- `llm_client/execution/structured_runtime.py`
- `tests/test_structured_attempts.py`
- `tests/test_result_finalization.py` if cache semantics require coverage
- generated API documentation if the public result surface is rendered there
- `docs/plans/CLAUDE.md`, `docs/CONCERNS.md`, and this plan

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_structured_attempts.py` | `test_native_schema_runtime_persists_failed_attempt_before_retry_success` | Both provider-reported prices are summed and coverage is true |
| `tests/test_structured_attempts.py` | `test_async_native_schema_runtime_preserves_failed_attempt` | Sync and async logical-cost semantics match |
| `tests/test_structured_attempts.py` | `test_sync_timeout_attempt_is_visible_before_retry_success` | Known cost is retained but coverage is false |
| `tests/test_structured_attempts.py` | `test_native_schema_runtime_persists_litellm_pre_return_validation_failure` | Raw attempt history does not imply invented price coverage |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_structured_runtime.py` | Clean structured calls retain existing cost and response semantics |
| `tests/test_result_finalization.py` | Cache hits add no marginal spend |
| `tests/test_cost_source_ordering.py` | Provider-reported cost remains authoritative |

Existing structured runtime, attempt-ledger, result finalization, cost, and
observability tests must remain green.

## Acceptance Criteria

- [x] Invalid-response repair returns and logs all observed attempt spend.
- [x] Coverage is true only when every started native attempt was priceable.
- [x] Unknown or ambiguous attempt spend remains explicit.
- [x] The selected response, model identity, and attempt receipt remain intact.
- [x] Sync and async paths have identical accounting semantics.
- [x] Focused and feasible repository gates pass.
- [x] Adversarial audit, cleanup, and concern triage are complete.

## Closeout Evidence

- The plan gate passed all 50 declared structured-attempt, runtime,
  finalization, and cost-source tests.
- The wider affected surface passed 126 tests.
- Sync and async invalid-response repairs each returned and logged the exact
  sum of two provider-reported prices; timeout and LiteLLM pre-return
  validation controls retained known spend with coverage false.
- The Cybernetic consumer's strict runtime accepted the complete receipt,
  retained unknown-spend refusal, passed strict typing and its full repository
  gate, and exposed the recovered live trial through the deployed browser.
- Focused Ruff and relationship validation pass. Direct strict mypy reports
  only the registered `core.client` re-export baseline.
- Repository-wide collection remains unavailable because optional
  `data_contracts` and `prompt_eval` packages are absent. A broader collected
  grouping also reproduced the registered shared-SQLite lifecycle crash; no
  completion claim relies on either unavailable baseline.

## Rollback

Remove the additive coverage field and native ledger while retaining the
existing attempt history. Strict consumers will then resume rejecting every
recovered retry as aggregate-cost-unknown.
