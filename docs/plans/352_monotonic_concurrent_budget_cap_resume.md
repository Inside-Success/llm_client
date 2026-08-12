# Plan #352: Monotonic Concurrent Budget-Cap Resume

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Process Tracing Plan 038 full revolution-corpus adjudication

## Gap

Plan 335 intentionally requires every call sharing a `reserved_concurrent`
scope to present the same normalized root cap. That prevents conflicting
callers, but it also prevents a long-running checkpointed workload from
resuming after an analyst deliberately raises an insufficient cap. Process
Tracing reproduced this boundary after 32 reviewed revolution candidates: the
shared ledger correctly rejected `$11.00` because the scope was created at
`$8.36304534375`, before any new provider call occurred.

## Decision

Add one explicit compare-and-set administration operation:

```python
raise_budget_scope_max_budget(
    scope_trace_id="study/run-1",
    expected_max_budget=8.36304534375,
    new_max_budget=11.0,
)
```

The operation is transactional in the existing SQLite reservation owner. It:

- requires an existing scope and the caller's exact expected current cap;
- permits only an equal or greater normalized replacement;
- is idempotent when the same successful mutation is retried;
- preserves settled calls, active reservations, and available-budget math;
- causes stale callers presenting the old cap to continue failing loud; and
- makes no provider call and stores no prompt, response, credential, or error
  text.

This revises Plan 335's immutable-cap rule only through the explicit operation.
Ordinary call admission and `get_budget_scope_snapshot` still require an exact
cap match; there is no implicit increase, decrease, or fallback.

## Acceptance

- [ ] Focused real-SQLite tests cover successful raise, active-reservation
      preservation, idempotent retry, missing scope, stale expectation, and
      decrease rejection.
- [ ] Plan 335's focused reservation/call/runtime tests remain green.
- [ ] A clean Process Tracing resume raises the same scope, reuses its first
      four producer/reviewer checkpoints, and admits the next batch without
      discarding settled cost.
- [ ] The change merges to personal `main`; downstream runtime pinning remains
      the consumer repository's explicit responsibility.

## Non-Claims

This does not authorize spend, choose a new cap, guarantee provider billing,
cancel an overrun, coordinate separate databases, or change sequential-budget
semantics.
