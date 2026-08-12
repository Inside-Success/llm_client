# Plan #356: Instructor Structured-Attempt Ledger

**Status:** Implemented — awaiting one post-merge Luna acceptance canary
**Type:** bounded maintenance repair
**Priority:** Critical
**Blocked By:** None
**Blocks:** `research_v3` Plan #25 evidence-complete Luna comparison

## Observed Gap

The fresh Luna baseline call `llmcall_b7ab73e200414788bd59711ea644f6be`
completed through the Instructor structured-output path with a terminal call
row, `cache_hit=false`, and observed cost, but emitted no
`structured_attempt_events`. The outer lifecycle was singular after Plan #354,
yet the runtime could not prove how many provider generations Instructor used.

## Outcome

Instructor structured calls use the same append-only attempt contract as
native-schema and Responses paths:

- one shared-kernel attempt owns one Instructor provider generation;
- the attempt emits `started -> received -> validated` on success;
- exact message content or one tool call's function arguments supply the raw
  structured bytes; parsed Pydantic output is never substituted for raw bytes;
- shared retry/fallback policy, cost custody, logical-call identity, and
  singular terminal lifecycle remain unchanged; and
- selected-attempt receipt reads accept the explicit `instructor` path only
  when its terminal row and attempt history agree.

Instructor's internal retry count is fixed to one. Any retry or fallback is
therefore visible to the existing shared retry kernel and bounded by the
caller's declared `num_retries`, deadline, and budget.

## Non-Goals

- No model, routing, or provider-policy change.
- No reclassification of Plan #25's already-invalid baseline as valid.
- No claim that Instructor is provider-native JSON Schema.
- No relaxation of raw-artifact, schema, identity, or receipt checks.

## Acceptance

- Sync and async Instructor successes retain exact
  `started -> received -> validated` attempt histories.
- The selected-attempt receipt joins an Instructor terminal row to its exact
  raw payload hash.
- Instructor receives `max_retries=1`; the shared kernel remains retry owner.
- Native-schema, Responses, terminal lifecycle, and selected-attempt suites
  remain green in fresh processes.
- The first new live Luna call after merge has one start, one completed
  terminal, one provider attempt, and no external action.

## Required Tests

- `tests/test_structured_attempts.py::test_sync_instructor_attempt_is_receipted`
- `tests/test_structured_attempts.py::test_async_instructor_attempt_is_receipted`
- `tests/test_structured_attempts.py::test_sync_instructor_retry_is_owned_by_shared_kernel`
- `tests/test_structured_attempts.py::test_sync_instructor_postvalidation_failure_never_regenerates`
- `tests/test_selected_attempts.py`
- `tests/test_structured_runtime.py`
- `tests/test_client_lifecycle.py`

## Files

- `llm_client/execution/structured_runtime.py`
- `llm_client/observability/structured_attempts.py`
- `llm_client/observability/selected_attempts.py`
- `tests/test_structured_attempts.py`
- `docs/adr/0007-observability-contract-boundary.md`
- `docs/adr/0010-cross-project-runtime-substrate.md`
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`
- `docs/plans/CLAUDE.md`

## Implementation Evidence (2026-08-12)

- Sync and async Instructor calls now emit exact
  `started -> received -> validated` attempt histories and strict selected-
  attempt receipts over the retained raw-content hash.
- Instructor receives one internal attempt; a transient-failure regression
  proves the shared kernel owns retry, recovery disposition, and global
  ordinals.
- A post-validation hook-failure regression proves local finalization cannot
  trigger another provider generation.
- The four affected suites pass together: 107 tests. The machine-declared Plan
  #356 set passes: 89 tests. Ruff, relationship validation, generated API
  reference, required-reading gates, and diff hygiene pass.
- The repository-wide suite collected 2,113 tests: 2,089 passed, three skipped,
  12 deselected, and nine failed. The nine failures are the inherited
  full-process Instructor mock-cache contamination in `tests/test_client.py`
  and two pre-existing doc-coupling policy fixtures; no Plan #356 test failed.
- Code-diff review verdict: `pass` after adding retry-ownership and
  no-regeneration controls and removing unrelated formatter churn.

Remaining acceptance is exactly one post-merge Luna canary with one public
start, one terminal completion, one Instructor provider attempt, a readable
selected-attempt receipt, and zero external actions.
