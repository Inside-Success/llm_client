# Plan #113: Responses Structured Custody Reconciliation

**Status:** Implemented (focused verified; repository completion gate unavailable)
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** onto-canon6 Plan 0145 reviewed preprocessing replay

---

## Frame

Make direct Responses-API structured calls produce the same exact, replayable
selected-attempt custody contract as provider-native Completions calls without
regressing hard deadlines, validation repair, fallback, or all-attempt cost
coverage already on `main`.

## Gap

**Current:** Responses structured calls can validate and retry, but do not emit
the structured attempt lifecycle or retain exact raw output. An older isolated
branch added basic custody before later deadline, validation-repair, and
all-attempt-cost changes landed, so pinning that branch regresses the canonical
runtime.

**Target:** Sync and async Responses calls use one logical-call-global attempt
ordinal and cost ledger across retry and model fallback. Each dispatched
attempt records `started`, then either bounded execution failure or exact raw
`received`, and finally validation plus the retry kernel's actual disposition.
The selected-attempt reader accepts either supported provider-native path only
when the terminal row and complete lifecycle agree.

**Why:** Cross-project consumers must be able to recover a paid validated
Responses output from durable raw custody without executing the model again or
pinning a stale runtime revision.

## Target Outcome

A provider-free sync and async fixture returns a structured Responses result,
reopens its exact retained bytes through `logical_call_id`, and validates a
receipt whose path, schema, model, terminal row, and lifecycle agree. A
schema-invalid first response followed by a repair response retains both raw
outputs, a complete recovery decision, and aggregate cost.

Passing these fixtures does not certify a provider, prove hostile-process
security, or authorize replay spend.

## References Reviewed

- `CLAUDE.md` and subtree instructions.
- ADRs 0001, 0002, 0003, 0004, 0007, 0009, 0010, 0012, 0013, and 0014.
- Plans 97, 101, 102, 109, and 111.
- `llm_client/execution/structured_runtime.py`
- `llm_client/observability/structured_attempts.py`
- `llm_client/observability/selected_attempts.py`
- `tests/test_structured_raw_artifacts.py`
- Historical custody commit `cf12c9833c9b0146ae1d5f8bb14f2fc7f95e8ce0`
- Canonical base `fad49d9840ca086bb4f7c7744728e69ce83b24a6`

## Boundaries And Rules

- The structured runtime owns attempt identity, lifecycle, retry disposition,
  exact raw-artifact writes, and cost aggregation.
- The selected-attempt reader owns fail-loud reconciliation between the
  terminal row, snapshot, and attempt history.
- Raw content remains in the configured artifact store; observability events
  retain only hashes and references.
- A response that validated is terminal for provider retry even if a later
  hook, cache, or persistence operation fails.
- A failed attempt followed by success must include one `recovery_decided`
  event whose `retry` or `fallback` value agrees with the next model.
- Cached calls do not fabricate provider-attempt custody.

## Files Affected

- `llm_client/execution/structured_runtime.py`
- `llm_client/observability/structured_attempts.py`
- `llm_client/observability/selected_attempts.py`
- `tests/test_structured_raw_artifacts.py`
- `tests/test_selected_attempts.py`
- generated API documentation if doc generation changes it
- `docs/plans/CLAUDE.md`
- this plan

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_structured_raw_artifacts.py` | `test_responses_api_selected_output_has_exact_raw_custody` | Exact raw bytes and complete selected lifecycle |
| `tests/test_structured_raw_artifacts.py` | `test_async_responses_api_selected_output_has_exact_raw_custody` | Sync/async parity |
| `tests/test_structured_raw_artifacts.py` | `test_responses_api_validation_repair_retains_both_attempts_and_cost` | Both attempts, recovery decision, and aggregate cost survive |
| `tests/test_structured_raw_artifacts.py` | `test_responses_api_fallback_keeps_one_logical_attempt_history` | Model fallback keeps contiguous global ordinals and honest incomplete-cost coverage |
| `tests/test_selected_attempts.py` | `test_reads_responses_attempt_when_terminal_path_agrees` | Reader accepts matching Responses evidence and rejects contradictions through the existing negative matrix |
| `tests/test_selected_attempts.py` | `test_one_attempt_with_inconsistent_execution_paths_rejects` | One attempt cannot switch execution paths inside its lifecycle |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_structured_attempts.py` | Attempt lifecycle and aggregate cost remain intact |
| `tests/test_structured_runtime.py` | Current structured call and retry behavior remains intact |
| `tests/test_result_finalization.py` | Validated-response finalization stays terminal |
| `tests/test_cost_source_ordering.py` | Cost-source precedence remains intact |

## Acceptance Criteria

- [x] Sync and async Responses outputs reopen byte-for-byte by logical call.
- [x] Retry/fallback histories are contiguous and fail loud when incomplete.
- [x] Every priceable Responses retry contributes to aggregate cost.
- [x] Selected-attempt reads bind the terminal row to the actual provider-native path.
- [x] Focused tests, plan gate, changed-file lint, and feasible repository gates pass.
- [ ] onto-canon6 pins a full canonical commit containing this capability.

## Verification Evidence

- Plan gate: 110 passed.
- Changed-file Ruff: passed.
- Relationship validation: passed.
- Generated API reference refreshed.
- `make check` stops at the inherited repository-wide Ruff baseline (305
  findings outside this change).
- The mandatory completion script stops during collection because the optional
  `langgraph` package is absent; it collected 1,842 tests before
  `tests/test_workflow_langgraph.py` failed to import.
- Direct Mypy traversal also reproduces the registered cross-package typing
  baseline; no changed-file Ruff or focused behavioral failure remains.

## Rollback

Revert Plan 113 and keep Responses selected-attempt custody unsupported. Do not
restore the stale cross-project dependency pin.
