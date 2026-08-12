# Plan #352: Monotonic Concurrent Budget-Cap Resume

**Status:** Complete
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

- [x] Focused real-SQLite tests cover successful raise, active-reservation
      preservation, idempotent retry, missing scope, stale expectation, and
      decrease rejection.
- [x] Plan 335's focused reservation/call/runtime tests remain green.
- [x] A clean Process Tracing resume raises the same scope, reuses its first
      four producer/reviewer checkpoints, and admits the next batch without
      discarding settled cost.
- [x] The change merges to personal `main`; downstream runtime pinning remains
      the consumer repository's explicit responsibility.

## Adoption Evidence

PR #143 merged the operation to personal `main` at
`a819730c888fd0842c5592059b823ff096248bb6` after 48 focused tests passed.
Process Tracing Plan 038 pinned that exact revision, raised the existing
`plan038-revolution-adjudication-full-v1` scope from `$8.36304534375` to
`$11.00`, replayed the first four producer/reviewer checkpoint pairs, admitted
the next batch, and ultimately completed all 342 batch pairs. The terminal
snapshot records `$6.28355` settled, zero active reservations, and `$4.71645`
available. This establishes downstream adoption and checkpoint preservation.

The same run exposed a separate limitation outside this plan: twelve provider
attempts inside four terminal structured failures retain `$0.081136555` of
provider-reported cost in failure custody, but their logical call rows have
null cost and their reservations are released rather than settled. The cap-
raise operation is complete; complete failed-attempt settlement requires a
successor budget-accounting change.

## Non-Claims

This does not authorize spend, choose a new cap, guarantee provider billing,
cancel an overrun, coordinate separate databases, or change sequential-budget
semantics.
