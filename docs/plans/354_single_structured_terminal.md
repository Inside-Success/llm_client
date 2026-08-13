# Plan #354: Single Structured-Call Terminal Lifecycle

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** `research_v3` Plan #25 priority-neutral planner comparison

---

## Gap

**Observed:** Public sync and async structured calls use a lifecycle-owning
wrapper, but the private structured runtime also writes a terminal lifecycle
row while persisting the terminal `llm_calls` record. A successful Plan #24
call therefore retained one `started` event and two `completed` events for one
logical call. Provider dispatch, response, validation, and semantic output were
singular.

**Target:** The public wrapper is the sole owner of public call terminal
lifecycle. The private structured runtime continues to bind the returned
logical-call ID and persist the terminal call row, but does not emit a second
terminal lifecycle event.

## Root Cause

`_run_sync_public_call()` and `_run_async_public_call()` emit the public
`started -> completed|failed|cancelled` lifecycle. Both private structured
runtime implementations wrap `_base_log_call_event()` and additionally call
`record_call_lifecycle_event()` with `completed` or `failed`. Existing wrapper
tests mock the private runtime and therefore never exercise this composition.

## Boundary

- Remove only the private runtime's duplicate terminal lifecycle writes.
- Preserve terminal `llm_calls` persistence, structured-attempt events,
  logical-call binding, provider/parse events, Foundation projection, budget
  settlement, and public wrapper lifecycle behavior.
- Add composed sync and async regressions that enter through the public API and
  use a fake provider beneath the real structured runtime.
- Do not backfill or mutate historical duplicate rows.

## Pass / Fail

- **Pass:** a public structured success records exactly one `started` and one
  `completed` terminal event for its logical call in both sync and async paths;
  structured provider/validation events and one terminal call row remain.
- **Fail:** a duplicate terminal remains, a public call loses its terminal, a
  private persistence failure becomes silent, or retry/provider behavior
  changes.

## Files Affected

- `llm_client/execution/structured_runtime.py`
- `tests/test_client_lifecycle.py`
- `docs/plans/354_single_structured_terminal.md`
- `docs/plans/CLAUDE.md`

## Required Tests

- composed sync public structured success lifecycle;
- composed async public structured success lifecycle;
- existing public lifecycle suite;
- structured runtime and structured-attempt suites;
- Ruff and required-reading checks for changed files.

## Non-Claims

This does not change provider execution, retry/fallback, model identity, schema
validation, call snapshots, cost settlement, historical observations, or the
meaning of nonterminal structured-attempt phases.

## Completion Evidence (2026-08-12)

- The sync and async private structured runtimes no longer emit terminal call
  lifecycle rows while persisting `llm_calls`; the public wrappers remain the
  single terminal owner.
- New composed-path controls enter through the public structured APIs, mock
  only provider transport, and verify one `started`, one `completed`, and one
  terminal call row for the same logical call in both sync and async modes.
- Fresh-process verification passed: 23 public lifecycle tests, 32 structured
  runtime tests, 18 structured-attempt tests, and 38 lifecycle-ledger plus
  selected-attempt tests.
- Ruff passes for both changed Python files, required-reading gates pass, and
  `git diff --check` is clean. The large runtime retains pre-existing formatter
  drift rather than receiving an unrelated whole-file rewrite.
- The repository-wide run in the declared `.venv` collected 2,097 tests: 2,082
  passed, three skipped, and 12 failed. Those failures reproduce the repository's
  existing cross-test Instructor/cache contamination and doc-coupling fixture
  drift; affected Plan #354 suites pass when isolated in fresh processes.
