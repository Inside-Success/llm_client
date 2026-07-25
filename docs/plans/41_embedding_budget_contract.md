# Plan #41: Embedding Budget Contract

**Status:** ✅ Complete

**Verified:** 2026-07-25
**Verification Evidence:**
```yaml
completed_by: scripts/complete_plan.py
timestamp: 2026-07-22T13:05:02Z
tests:
  unit: 1794 passed, 3 skipped, 12 deselected, 13 warnings in 192.91s (0:03:12)
  e2e_smoke: skipped (no e2e directory)
  e2e_real: skipped (--skip-real-e2e)
  doc_coupling: passed
commit: 276363f
```
Reconciliation verification on current main: 347 focused and adjacent tests
passed; Ruff passed.
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** onto-canon6 Plan 0162 live semantic candidate retrieval

---

## Gap

**Current:** `embed()` and `aembed()` accept `task` and `trace_id`, but
`max_budget` is not a named argument and therefore falls through `**kwargs` to
the provider. Embedding calls do not reuse the shared tag normalization or
pre-dispatch trace-budget check.

**Target:** Both embedding entrypoints expose an additive keyword-only
`max_budget` argument, consume it inside `llm_client`, and apply the existing
`require_tags()` and `check_budget()` contracts before provider dispatch.
`max_budget=0` remains the established unlimited setting, so budget is a safety
fuse rather than a spend-optimization gate.

**Why:** Cross-project embedding consumers need the same explicit task, trace,
and budget call contract as other shared runtime surfaces without leaking
client policy keywords into provider payloads.

---

## Design

**Request mode:** plan and implement.

**Profile:** Small, production-internal. This is an additive shared public API
change with deterministic behavior and no new state, provider, route, or result
model.

**Landscape disposition:** inline. Reuse the installed
`require_tags()`/`check_budget()` substrate rather than creating an embedding-
specific budget mechanism. `get_cost(trace_id=...)` already sums successful
LLM and embedding rows.

### Contract And Invariants

1. `max_budget` is keyword-only and defaults to `None` for backward
   compatibility.
2. Shared tag normalization owns numeric validation and strict-mode missing-tag
   failure.
3. `0` means unlimited; a positive value rejects dispatch when the trace has
   already spent at least that amount.
4. `task`, `trace_id`, and `max_budget` never enter LiteLLM provider kwargs.
5. Sync and async entrypoints have identical behavior.
6. Embedding routing, retries, cost recording, vectors, and `EmbeddingResult`
   remain unchanged.

### Non-Goals

- Predict or reserve the cost of one pending provider call.
- Add an embedding cache to `llm_client`.
- Change model routing, retry policy, or provider selection.
- Introduce a default finite monetary limit.
- Change chat, structured, stream, agent, or replay budgets.

### Failure And Rollback

- Strict-mode omission or a nonnumeric budget fails before provider dispatch.
- An exhausted positive trace budget raises the existing
  `LLMBudgetExceededError` before provider dispatch.
- Rollback is removal of the additive parameter and two runtime guard calls;
  no stored data or migration is involved.

---

## References Reviewed

- `CLAUDE.md` — required call and public API rules.
- `llm_client/core/client.py` — public embedding facade.
- `llm_client/execution/embedding_runtime.py` — sync/async provider boundary.
- `llm_client/execution/call_contracts.py` — shared tag and budget behavior.
- `llm_client/observability/query.py` — combined LLM/embedding trace cost.
- `docs/adr/0010-cross-project-runtime-substrate.md` — embedding and
  observability ownership.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — explicit
  fresh-budget authority and replay separation.
- `docs/adr/0001-model-identity-v0.md` — canonical requested and resolved model
  identity.
- `docs/adr/0002-routing-config-precedence.md` — explicit call arguments and
  routing precedence.
- `docs/adr/0003-warning-taxonomy.md` — stable warning and policy evidence.
- `docs/adr/0004-result-model-semantics-migration.md` — result-model
  compatibility.
- `docs/adr/0009-long-thinking-background-polling.md` — timeout ownership
  boundaries.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` —
  provider capability and local evidence authority.
- `docs/plans/117_explicit_reasoning_policy.md` — explicit normalized execution
  controls; embeddings do not add a reasoning control.

---

## Files Affected

- `llm_client/core/client.py` (modify)
- `llm_client/execution/embedding_runtime.py` (modify)
- `tests/test_embedding_runtime.py` (create)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate)
- `docs/plans/CLAUDE.md` (modify)
- this plan

---

## Plan

### Steps

1. Add the named public and internal sync/async parameter.
2. Normalize tags and check the trace budget before route/provider dispatch.
3. Prove unlimited, finite rejection, strict omission, provider isolation, and
   async parity without network access.
4. Regenerate the public API reference and run focused/shared checks.

### Slice 1 — Explicit Embedding Call Guard

One additive contract across the public facade and runtime. It is complete
when an unlimited onto-canon6-style call dispatches, a finite exhausted trace
does not dispatch, missing strict tags fail, and no client-only fields reach
LiteLLM in either sync or async mode.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_embedding_runtime.py` | `test_embed_consumes_unlimited_budget_without_provider_leak` | explicit `0` dispatches and client-only fields stay local |
| `tests/test_embedding_runtime.py` | `test_embed_rejects_exhausted_trace_before_provider_dispatch` | positive finite budget uses shared preflight |
| `tests/test_embedding_runtime.py` | `test_embed_strict_mode_requires_budget_before_provider_dispatch` | missing strict contract fails loud |
| `tests/test_embedding_runtime.py` | `test_aembed_consumes_unlimited_budget_without_provider_leak` | async parity |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_client.py` | public facade and call contracts remain compatible |
| `tests/test_io_log.py` | embedding cost/trace persistence remains compatible |

The generated API reference check must also pass so public signatures match
the implementation.

---

## Acceptance Criteria

- [x] Named `max_budget` is present on `embed()` and `aembed()`.
- [x] `max_budget=0` dispatches without imposing a spend gate.
- [x] Finite exhausted budgets and strict missing tags fail before dispatch.
- [x] Client-only task/trace/budget fields never reach the provider.
- [x] Sync and async focused tests pass.
- [x] Public API reference is regenerated and checks pass.
- [x] Applicable existing tests, type checks, and lint pass or inherited debt is
  reported precisely.
- [x] Verified changes are committed and pushed with the embedding-budget plan.

---

## Notes

Passing this plan proves the shared embedding call contract. It does not prove
an embedding provider route, semantic retrieval quality, onto-canon6 live
integration, caching, or a document extraction.
