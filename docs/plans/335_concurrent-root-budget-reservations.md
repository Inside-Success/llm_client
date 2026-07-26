# Plan #335: Concurrent Root-Budget Reservations

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** Plan #333
**Blocks:** DIGIMON Plan #182

---

## Assignment Contract

This plan is intentionally prescriptive. The implementer may choose local
function decomposition and names for private helpers, but must not change the
public semantics, persistence schema, money rounding, failure behavior, slice
order, or acceptance tests without Brian's approval and a plan revision.

Implement in a dedicated `llm_client` worktree based on freshly fetched
personal `main`. Do not implement in DIGIMON from this worktree.

## Objective

Allow independent LLM calls under one request root to execute concurrently
without allowing their declared reservations to exceed the request budget.
Admission must be atomic across threads and processes sharing the configured
SQLite observability database.

The intended consumer is DIGIMON Plan #182, which currently keeps a
project-local settled-cost ledger because Plan #333 deliberately serializes
bounded scoped calls.

## Canonical Example

Given:

- root scope `digimon.query.abc`
- root budget `$0.20`
- already settled cost `$0.04`
- graph child reservation `$0.08`
- wiki child reservation `$0.08`

Then both children may be admitted concurrently:

1. graph atomically observes `$0.04 + $0.00 + $0.08 = $0.12` and reserves
   `$0.08`;
2. wiki atomically observes `$0.04 + $0.08 + $0.08 = $0.20` and reserves
   `$0.08`;
3. a third child requesting `$0.01` is rejected before provider dispatch;
4. when graph settles at `$0.06` and wiki at `$0.07`, their reservations are
   closed and the scope reports `$0.17` settled, `$0.00` active, `$0.03`
   available.

Negative example: with `$0.04` settled, two concurrent `$0.10` reservation
requests cannot both pass. Exactly one is admitted.

## Claim and Explicit Non-Claims

Passing this plan licenses:

> `llm_client` atomically limits the sum of settled cost and active declared
> reservations for one trace scope across processes sharing its SQLite store.

It does **not** license:

- a claim that provider final spend can never exceed the root budget;
- automatic selection of a reservation amount for a caller;
- distributed coordination across different SQLite files;
- cancellation of a provider call that exceeds its declared reservation;
- replacement of DIGIMON's ledger before Plan #182 passes.

An actual call cost above its reservation is detected after settlement and
fails loudly, but the provider spend has already occurred.

---

## Gap

**Current:** Plan #333 validates root/descendant trace relationships and
aggregates settled prefix cost. A process-local set allows only one bounded
call per scope. `budget_reservation` is checked but is not persisted, so it
cannot safely admit parallel calls.

**Target:** Add an explicit `reserved_concurrent` scope mode backed by
transactional SQLite reservations. Keep Plan #333's current `sequential` mode
as the compatibility default.

## References Reviewed

Code and current contract surfaces reviewed before fixing this design:

- `llm_client/execution/call_contracts.py`,
  `llm_client/execution/call_wrappers.py`, and
  `llm_client/execution/stream_runtime.py` — Plan #333's process-local lease
  lifecycle and every public terminal path.
- `llm_client/observability/query.py` and `llm_client/io_log.py` — settled
  prefix-cost queries, SQLite locking, migrations, and compatibility facade.
- `llm_client/core/client.py` and `llm_client/core/errors.py` — public
  entrypoints and typed error hierarchy.
- Plan #333 and its personal merge
  `2b627ff525125bec21999c730349cb9812924dae` — completed sequential scoped
  behavior.
- Plan #105 — personal-upstream and Inside-Success fork ancestry/tree
  synchronization rule.
- `docs/adr/0001-model-identity-v0.md`,
  `docs/adr/0002-routing-config-precedence.md`,
  `docs/adr/0003-warning-taxonomy.md`, and
  `docs/adr/0004-result-model-semantics-migration.md` — identity, explicit
  precedence, fail-loud integrity, and result compatibility.
- `docs/adr/0007-observability-contract-boundary.md`,
  `docs/adr/0010-cross-project-runtime-substrate.md`, and
  `docs/adr/0012-shared-data-plane-boundary.md` — shared ownership,
  metadata-only persistence, and cross-project data-plane boundaries.
- `docs/adr/0009-long-thinking-background-polling.md` and
  `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` — long-running
  and streaming lifecycle requirements.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` and
  `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` —
  meaningful control identity, replay evidence, and provider-safe controls.
- `docs/plans/110_provider-capabilities-opus-ban.md` and
  `docs/plans/117_explicit_reasoning_policy.md` — normalized public controls,
  fallback-chain enforcement, and pre-dispatch validation precedent.

## Public Contract

Add these explicit keyword-only parameters to text, structured, sync, async,
and streaming public entrypoints:

```python
budget_scope_trace_id: str | None = None
budget_scope_mode: Literal["sequential", "reserved_concurrent"] = "sequential"
budget_reservation: float = 0.0
```

Rules:

1. `budget_scope_trace_id=None` requires `budget_scope_mode="sequential"` and
   preserves exact-trace behavior.
2. `sequential` preserves Plan #333 behavior. A positive scoped budget admits
   only one in-flight call per process.
3. `reserved_concurrent` requires:
   - non-empty `budget_scope_trace_id`;
   - `max_budget > 0`;
   - finite `budget_reservation > 0`;
   - `budget_reservation <= max_budget`;
   - enabled and writable SQLite observability.
4. A missing, disabled, or unwritable durable store fails before provider
   dispatch. Never fall back to sequential or exact-trace enforcement.
5. Scope must equal `trace_id` or be its slash-delimited ancestor.
6. All calls reusing a scope must declare the same normalized root budget.
7. Retries and internal fallback legs of one public call share one reservation.
   A later application-level fallback is a new reservation.
8. All three control fields are stripped before provider dispatch.
9. `max_budget=0` remains unlimited only in `sequential` mode.

Unknown mode values fail with `ValueError`.

## Money Normalization

Persistence and comparisons use integer micro-USD:

```python
MICRO_USD = 1_000_000
normalized_budget = floor(Decimal(str(max_budget)) * MICRO_USD)
normalized_reservation = ceil(Decimal(str(budget_reservation)) * MICRO_USD)
normalized_settled_cost = ceil(Decimal(str(settled_cost)) * MICRO_USD)
```

Reject booleans, NaN, infinity, negative values, and a positive input that
normalizes to zero. Do not compare budget floats directly.

## Domain Objects

Implement frozen typed records (dataclass or Pydantic, consistent with the
owning module):

```python
BudgetScopeMode = Literal["sequential", "reserved_concurrent"]

BudgetScopeSnapshot(
    scope_trace_id: str,
    max_budget_microusd: int,
    settled_microusd: int,
    active_reserved_microusd: int,
    available_microusd: int,
)

BudgetReservationLease(
    reservation_id: str,
    scope_trace_id: str,
    call_trace_id: str,
    owner_id: str,
    reserved_microusd: int,
)
```

The lease is opaque to public consumers. Release and settlement are
idempotent. `owner_id` is a process-random UUID created once at import/runtime
initialization, not a PID and not caller-controlled.

Export this read-only public query:

```python
def get_budget_scope_snapshot(
    *,
    scope_trace_id: str,
    max_budget: float,
) -> BudgetScopeSnapshot: ...
```

It applies the same trace and money validation as admission, reads settled
prefix cost and active unexpired reservations from the configured SQLite
store, and returns normalized integer fields. If a scope row already exists,
its normalized budget must match. If no scope row exists, the function returns
a snapshot without creating one; admission remains the only operation that
creates a scope. A disabled or unreadable store raises
`LLMBudgetReservationStoreError`. This function never reserves money.

## Persistence Schema

Add metadata-only tables through the existing additive SQLite migration path:

```sql
CREATE TABLE IF NOT EXISTS budget_scopes (
    scope_trace_id TEXT PRIMARY KEY,
    max_budget_microusd INTEGER NOT NULL CHECK (max_budget_microusd > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    scope_trace_id TEXT NOT NULL,
    call_trace_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    reserved_microusd INTEGER NOT NULL CHECK (reserved_microusd > 0),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'settled', 'released_error', 'expired')
    ),
    created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    settled_cost_microusd INTEGER,
    FOREIGN KEY(scope_trace_id) REFERENCES budget_scopes(scope_trace_id)
);

CREATE INDEX IF NOT EXISTS idx_budget_reservations_active_scope
ON budget_reservations(scope_trace_id, status);

CREATE INDEX IF NOT EXISTS idx_budget_reservations_expiry
ON budget_reservations(status, expires_at);
```

Do not persist prompts, responses, exception messages, credentials, or provider
payloads in these tables.

## Atomic Admission Operation

Create the canonical implementation in
`llm_client/observability/budget_reservations.py`. `io_log.py` may expose
compatibility imports but must not own the business logic.

Within `_db_write_lock` and one SQLite `BEGIN IMMEDIATE` transaction:

1. mark expired active leases `expired`;
2. insert the scope row if absent, otherwise require an identical
   `max_budget_microusd`;
3. query settled prefix cost from `llm_calls` and `embeddings` using the same
   exact-or-`scope/%` semantics as `get_cost`;
4. sum active reservation micro-USD for the scope;
5. reject when
   `settled + active_reserved + requested_reservation > max_budget`;
6. insert the active reservation;
7. commit and return its lease.

On any exception, roll back. Reuse the existing bounded SQLite lock-retry
policy. Do not call the public `get_cost()` helper inside the transaction.

## Lease Lifetime and Crash Recovery

Create one process-wide lease keeper, not one thread per call:

- default lease TTL: 300 seconds;
- renewal interval: 30 seconds;
- the keeper tracks only locally owned active reservation IDs;
- renewal updates `heartbeat_at` and `expires_at` only when both
  `reservation_id` and `owner_id` match an active row;
- zero updated rows marks the local lease as lost;
- loss raises `LLMBudgetLeaseLostError` at the public call's next terminal
  boundary after normal call observability is recorded;
- a crashed process stops renewing, so another admission may mark the lease
  expired after its stored `expires_at`;
- tests inject a clock and invoke a single renewal cycle directly; tests must
  not sleep.

The keeper starts lazily on the first durable reservation and shuts down via
the existing client/process cleanup mechanism. Database renewal errors are
logged and mark affected leases lost; they are never swallowed as success.

## Terminal Semantics

Success:

1. runtime records the normal call result/cost;
2. settle the lease with the returned `LLMCallResult.cost`;
3. mark status `settled`;
4. if normalized actual cost exceeds the reservation, raise
   `LLMBudgetReservationOverrunError` after persistence.

Failure/cancellation:

1. runtime records its normal failure lifecycle;
2. mark the lease `released_error`;
3. re-raise the original error.

Streaming:

- the lease remains active until natural completion, iterator error, explicit
  `close()`/`aclose()`, or expiry;
- natural completion settles with `stream.result.cost`;
- iterator error or explicit close uses `released_error`;
- add idempotent `close()` and `aclose()` to lifecycle adapters;
- an unconsumed, unclosed stream is recovered only by lease expiry.

Never release the reservation before the normal call/stream terminal record is
written.

## Typed Errors

Add:

- `LLMBudgetLeaseLostError(LLMError)`
- `LLMBudgetReservationOverrunError(LLMBudgetExceededError)`
- `LLMBudgetReservationStoreError(LLMError)`

These errors are non-retryable and must never trigger provider fallback.
Insufficient available budget continues to raise `LLMBudgetExceededError`.

## Runtime Data Flow

```text
public call
  -> validate scope/mode/reservation
  -> SQLite BEGIN IMMEDIATE
     -> settled prefix cost + active reservations
     -> admit and persist lease | reject
  -> provider retries/fallbacks under one lease
  -> normal terminal observability
  -> settle/release lease
  -> return result | raise typed terminal error
```

## Shared-Capability Contract

| Advertised capability | Owner | Consumer | Observable acceptance |
|---|---|---|---|
| Concurrent root-budget admission | personal `llm_client` | DIGIMON Plan #182 through synchronized Inside-Success fork | A real DIGIMON graph/wiki parallel cohort dispatches both children while a third over-budget reservation is rejected |
| Crash-recoverable durable leases | `llm_client` SQLite budget module | every process sharing the DB | A killed worker's lease blocks before expiry and is reclaimable after deterministic expiry |
| Provider-safe control fields | `llm_client` public wrappers/runtimes | all providers | Provider mock sees none of the three budget control fields |

## Files Affected

- `llm_client/observability/budget_reservations.py` (create)
- `llm_client/observability/__init__.py` (export the required snapshot query)
- `llm_client/io_log.py` (additive schema/migration and compatibility exports)
- `llm_client/core/errors.py` (typed errors)
- `llm_client/core/client.py` (explicit public parameters)
- `llm_client/execution/call_contracts.py` (mode validation; retain sequential)
- `llm_client/execution/call_wrappers.py` (lease lifecycle)
- `llm_client/execution/stream_runtime.py` (stream lease lifecycle)
- `llm_client/execution/streaming.py` (explicit close/aclose if owned there)
- `tests/test_budget_reservations.py` (new)
- `tests/test_call_contracts.py`
- `tests/test_client_lifecycle.py`
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (generated)
- `docs/adr/0007-observability-contract-boundary.md` (reverify metadata boundary)
- this plan and plan index

Do not modify DIGIMON in this plan.

---

## Plan

## Risk-Ordered Slices

### Slice 1 — Atomic persisted admission boundary

**Classification:** boundary probe/enabler; it directly removes the concurrency
block but is not useful to DIGIMON until Slice 2 and Plan #182.

Implement schema, money normalization, scope consistency, atomic admission,
idempotent settlement/release, snapshot query, and typed store errors. Do not
wire provider calls yet.

Required tests:

| Test | Required behavior |
|---|---|
| `test_two_processes_cannot_overreserve_one_scope` | Two process workers start together; exactly one `$0.60` request under `$1.00` succeeds |
| `test_parallel_reservations_fill_but_do_not_exceed_available_budget` | Canonical `$0.20` example passes and third reservation fails |
| `test_scope_rejects_changed_root_budget` | Same scope with a different normalized cap fails |
| `test_money_normalization_is_conservative` | budget floors; reservation and settled cost ceil |
| `test_disabled_or_unwritable_store_fails_loud` | No in-memory/sequential fallback |
| `test_release_and_settlement_are_idempotent` | duplicate terminal calls do not corrupt sums |
| `test_expired_crashed_lease_is_reclaimable` | fake-clock expiry changes active to expired and permits admission |

Done when the tests pass against a temporary real SQLite file, focused Ruff
passes, `git diff --check` passes, and an adversarial pass verifies transaction
rollback and no secret/content persistence.

#### Slice 1 Completion Evidence (2026-07-25)

- Implemented the metadata-only `budget_scopes` and `budget_reservations`
  tables and the canonical `observability.budget_reservations` transaction
  boundary.
- `tests/test_budget_reservations.py`: 7 passed against a temporary real SQLite
  file, including two spawned processes contending for one `$1.00` scope.
- Focused Ruff passed for the new reservation module, its exports, typed errors,
  and its tests; `git diff --check` passed.
- The repository-wide `io_log.py` Ruff invocation still reports pre-existing
  import-layout and duplicate-key findings outside this slice. The reservation
  changes add no such finding.

### Slice 2 — Public runtime and stream integration

Wire the explicit public parameters, one lease per logical public call,
process-wide renewal, terminal settlement, typed overrun/lost-lease behavior,
and stream close semantics.

Required tests:

| Test | Required behavior |
|---|---|
| `test_parallel_public_calls_share_one_root_budget` | Two held provider calls are simultaneously in flight and their reservations are both visible |
| `test_retry_and_internal_fallback_reuse_one_reservation` | Reservation row count remains one |
| `test_provider_never_receives_budget_control_fields` | text, structured, sync, async, and stream paths |
| `test_success_settles_after_call_row_is_recorded` | terminal ordering is observable |
| `test_error_and_cancellation_release_after_failure_record` | no leaked active lease |
| `test_actual_cost_over_reservation_fails_after_settlement` | typed overrun, row retained |
| `test_lost_lease_fails_at_terminal_boundary` | no successful return after custody loss |
| `test_stream_close_and_aclose_release_idempotently` | abandoned stream has an explicit cleanup path |

Run Plan #333 tests unchanged to prove compatibility.

Done when public API docs regenerate, the focused lifecycle/budget suite passes,
and an isolated second pass finds no path that releases before terminal
observability or forwards control fields.

#### Slice 2 Completion Evidence (2026-07-25)

- Public text, structured, sync, async, and streaming entrypoints now expose
  `budget_scope_mode` and `budget_reservation`; `sequential` remains the
  default.
- One outer public-call lease covers internal retry/fallback work. Success
  settles after normal result/lifecycle observability; failure, cancellation,
  stream error, and explicit stream close release after terminal lifecycle
  emission.
- A process-wide daemon keeper renews only locally owned active durable leases;
  lost custody fails at the terminal boundary rather than returning a success.
- Focused zero-spend verification: 41 tests passed across reservation,
  call-contract, lifecycle, and text-runtime suites. The integrated held-call
  canary observed two concurrent children and rejected a third before runtime
  dispatch. Focused Ruff and `git diff --check` passed. Explicit `close()` and
  `aclose()` finalize in `finally`, so a provider cleanup error cannot leak a
  durable reservation.

### Slice 3 — Review, merge, and fork synchronization

1. Freeze the exact personal branch head after Slices 1–2.
2. Run the plan gate plus affected observability/runtime tests.
3. Open and merge a normal PR to personal `main`.
4. Fetch both remotes again.
5. Synchronize `Inside-Success/llm_client` using Plan #105's accepted rule:
   personal `main` must be an ancestor of Inside-Success `main`, and both heads
   must resolve to the identical Git tree. Use a normal branch and PR; never
   force-push.
6. Record both immutable merge SHAs in this plan.

The fork gate is not satisfied by equivalent-looking source files, an editable
checkout, or an unmerged branch.

#### Plan-number correction (2026-07-25)

This work was initially allocated as Plan #334 before a concurrently merged,
unrelated Plan #334 became visible on personal `main`. It was reallocated to
Plan #335 before PR merge; the former path was renamed rather than retained as
a duplicate authority. No implementation semantics changed.

## Verification Commands

## Required Tests

- `tests/test_budget_reservations.py` — durable SQLite admission, money
  normalization, expiry, two-process contention, and terminal idempotence.
- `tests/test_call_contracts.py` — sequential compatibility, concurrent-mode
  validation, and budget-control stripping.
- `tests/test_client_lifecycle.py` — concurrent public-call canary, terminal
  settlement/release ordering, provider-safe controls, and stream close.
- `tests/test_text_runtime.py` — direct runtime provider kwargs remain free of
  budget controls.

```bash
python scripts/meta/check_plan_tests.py --plan 335
pytest -q tests/test_budget_reservations.py tests/test_call_contracts.py \
  tests/test_client_lifecycle.py tests/test_text_runtime.py
ruff check <changed Python files>
python scripts/meta/generate_api_reference.py --write
git diff --check
git merge-base --is-ancestor <personal-main-sha> <inside-success-main-sha>
test "$(git rev-parse <personal-main-sha>^{tree})" = \
     "$(git rev-parse <inside-success-main-sha>^{tree})"
```

Do not run paid provider calls. All implementation evidence is zero-spend.

## Acceptance Criteria

- [x] Canonical and negative examples pass against real temporary SQLite.
- [x] Concurrent admission is atomic across processes sharing one DB.
- [x] Sequential mode remains backward compatible.
- [x] Reserved-concurrent mode cannot run without durable storage and a
      positive reservation.
- [x] Lease crash recovery and ownership loss fail as specified.
- [x] Retries/fallbacks reuse one reservation.
- [x] Result, error, cancellation, and stream terminal paths close leases in
      the required order.
- [x] Provider payloads contain no budget controls.
- [x] Personal and Inside-Success `main` satisfy the Plan #105 ancestry/tree
      rule at immutable SHAs.
- [x] DIGIMON has not yet removed its local ledger.

Completion evidence was refreshed on 2026-07-25: personal merge
`dc61e356a1191b595c76b277fa618b219294b21d` is an ancestor of Inside Success
merge `b78d86bc47bb787c6751dbdf8d7dddcfc51f4045`, and both commits have the
same Git tree. DIGIMON still retains `_QueryBudgetLedger`; removal remains a
downstream Plan #182 decision.

## Rollback

Revert the Plan #335 merge with new commits on both remotes. Existing callers
remain on default `sequential` behavior. Do not delete the new tables during
rollback; they are additive metadata and older code ignores them. Plan #182
must remain blocked or restore its prior pin/ledger before either fork reverts.
