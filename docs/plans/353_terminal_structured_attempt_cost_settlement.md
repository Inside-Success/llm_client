# Plan #353: Terminal Structured-Attempt Cost Settlement

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Complete reserved-concurrent budget accounting for structured workloads

---

## Gap

**Current:** Native structured execution aggregates the cost of every returned
provider response into successful `LLMCallResult` objects. When validation
repairs exhaust, the same private attempt ledger is discarded: the terminal
call row has null cost and the concurrent reservation is marked
`released_error`. Process Tracing Plan 038 retained twelve fully returned
attempts across four such failures with `$0.081136555` of provider-reported cost
outside both the call-cost columns and settled budget scope.

**Target:** Carry complete attempt-cost accounting through a terminal structured
error. Persist the aggregate on the failed logical-call row and settle a durable
reservation only when every dispatched attempt has a returned, priceable
response. Preserve `released_error` for pre-response, partially priced,
cancelled, and otherwise incomplete failure paths.

**Why:** A budget ceiling that drops known failed-attempt spend can admit work
past its stated aggregate bound. The runtime already owns the required evidence;
the fix should expose and consume that evidence rather than parse exception
strings or estimate charges.

---

## References Reviewed

- `llm_client/execution/structured_runtime.py` — private attempt-cost owner and
  terminal structured-error logging.
- `llm_client/execution/call_wrappers.py` — public terminal lifecycle and budget
  release/settlement boundary.
- `llm_client/observability/budget_reservations.py` — canonical durable budget
  transaction owner.
- `llm_client/core/errors.py` — typed public-error boundary.
- `docs/plans/335_concurrent-root-budget-reservations.md` — existing success and
  failure reservation semantics.
- `docs/adr/0007-observability-contract-boundary.md` — metadata and durable
  budget persistence boundary.
- Process Tracing trace `plan038-revolution-adjudication-full-v1` — authentic
  reproduction with four terminal logical failures and twelve priceable
  attempts.
- `CLAUDE.md` — repository conventions.

---

## Files Affected

- `llm_client/core/errors.py` (modify)
- `llm_client/execution/call_wrappers.py` (modify)
- `llm_client/execution/structured_runtime.py` (modify)
- `tests/test_client_lifecycle.py` (modify)
- `tests/test_structured_raw_artifacts.py` (modify if the existing attempt-cost
  fixture is the narrowest authentic-shaped unit)
- `docs/plans/335_concurrent-root-budget-reservations.md` (modify)
- `docs/adr/0007-observability-contract-boundary.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Give a wrapped terminal error bounded numeric accounting fields populated
   directly from the native attempt ledger.
2. Persist a failed logical-call row with aggregate cost and cost source without
   changing its failed lifecycle classification.
3. Settle a reserved-concurrent lease from that error only when attempt-cost
   coverage is complete; otherwise preserve release semantics.
4. Cover sync and async wrappers, exact micro-USD rounding, incomplete coverage,
   and overrun behavior with focused tests.
5. Reconcile Plan 335 and ADR 0007 with the narrowed terminal semantics.

---

## Required Tests

| Check | What It Verifies |
|---|---|
| Sync structured terminal validation exhaustion | Failed row retains aggregate response cost and reservation settles it before the original error escapes. |
| Async structured terminal validation exhaustion | Async public boundary has identical accounting semantics. |
| Pre-response or incomplete attempt coverage | Reservation remains `released_error`; no cost is invented. |
| Reservation overrun | Observed cost persists and the typed budget overrun remains fail-loud. |
| Existing budget and structured suites | Successful, streaming, sequential, cache, and retry behavior remain unchanged. |

---

## Acceptance Criteria

- [ ] Failed structured rows retain exact observed aggregate cost and source.
- [ ] Fully covered structured failures settle durable reservations.
- [ ] Incomplete failures preserve release semantics and null/partial claim
      boundaries.
- [ ] Sync and async focused tests pass.
- [ ] Existing reservation and structured-attempt suites pass.
- [ ] Documentation distinguishes known spend from unknown provider billing.

---

## Non-Claims

This does not infer the cost of requests without a returned priceable response,
guarantee provider invoices, backfill historical ledgers, change retry counts,
or authorize a larger budget. Historical Process Tracing totals remain evidence
for the defect; mutating that completed lineage is out of scope.
