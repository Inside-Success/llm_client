# Plan #109: Structured-Call Hard Deadline

**Status:** Complete (2026-07-21)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Reliable long-running structured simulations

---

## Gap

**Current:** Structured calls pass a finite `timeout` to LiteLLM, but that
transport timeout is not an end-to-end deadline. A reproduced OpenRouter
DeepSeek call continued emitting lifecycle heartbeats beyond its 180-second
timeout, leaving a long-running caller apparently frozen.

**Target:** Every structured provider attempt has a client-enforced wall-clock
deadline in both sync and async runtimes. The shared default is 60 seconds;
callers can still override it or use the existing environment setting.

**Why:** Model switching belongs in `llm_client`, and long-running consumers
must not need provider-specific watchdog code to recover from a stalled
structured call.

---

## References Reviewed

- `CLAUDE.md` - repository workflow and runtime-substrate contract
- `docs/adr/0001-model-identity-v0.md` - requested/resolved model identity
- `docs/adr/0002-routing-config-precedence.md` - explicit override precedence
- `docs/adr/0003-warning-taxonomy.md` - operational warning semantics
- `docs/adr/0004-result-model-semantics-migration.md` - terminal model identity
- `docs/adr/0009-long-thinking-background-polling.md` - deliberate long-call exception
- `docs/adr/0010-cross-project-runtime-substrate.md` - shared retry/timeout ownership
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` - replayable call contract
- `llm_client/execution/structured_runtime.py` - sync/async structured provider attempts
- `llm_client/execution/timeout_policy.py` - shared timeout defaults and overrides
- `tests/test_client_lifecycle.py` - public structured timeout characterization

---

## Files Affected

- `llm_client/execution/structured_runtime.py` (modify)
- `llm_client/execution/timeout_policy.py` (modify)
- `llm_client/execution/retry.py` (modify)
- `llm_client/core/client.py` (modify documentation)
- `tests/test_structured_timeout_deadline.py` (create)
- `tests/test_client_lifecycle.py` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/92_structured_call_hard_deadline.md` (create)

---

## Plan

### Steps

1. Add focused failing tests for sync and async hard deadlines.
2. Add internal deadline helpers and apply them to every structured provider attempt.
3. Classify incomplete/chunked connection termination as a transient transport failure.
4. Change the shared structured default from 180 seconds to 60 seconds while preserving explicit and environment overrides.
5. Run targeted tests, the plan test gate, and the full repository checks.
6. Re-run the consuming simulator's 20-turn DeepSeek preset.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_structured_timeout_deadline.py` | `test_sync_deadline_raises_while_provider_is_still_blocked` | Sync provider hangs cannot outlive the configured attempt deadline |
| `tests/test_structured_timeout_deadline.py` | `test_async_deadline_cancels_blocked_provider_attempt` | Async provider hangs are cancelled at the configured attempt deadline |
| `tests/test_structured_timeout_deadline.py` | `test_sync_deadline_preserves_fast_result_and_exception` | Fast sync results and provider exceptions retain their normal semantics |
| `tests/test_structured_timeout_deadline.py` | `test_async_deadline_preserves_fast_result_and_exception` | Fast async results and provider exceptions retain their normal semantics |
| `tests/test_structured_timeout_deadline.py` | `test_incomplete_transport_response_is_retryable` | Abrupt chunked-response termination reaches shared retry policy |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_client_lifecycle.py` | Public default/override timeout behavior remains explicit |
| `tests/test_client.py` | Structured routing, retries, and provider kwargs remain compatible |
| `tests/test_timeout_policy.py` | Shared timeout environment precedence remains correct |

---

## Acceptance Criteria

- [x] Sync and async structured provider attempts stop waiting at the configured deadline
- [x] Shared structured default is 60 seconds and remains environment-configurable
- [x] Explicit `timeout=` still wins
- [x] Retry/fallback behavior receives a normal timeout exception
- [x] Required tests pass
- [x] Plan-scoped test gate passes; broader repository blockers are documented below
- [x] 20-turn DeepSeek consumer qualification reaches a terminal result without manual intervention

---

## Notes

The sync runtime cannot forcibly kill a Python thread that is blocked inside a
third-party HTTP stack. Its timed-out attempt therefore runs in a daemon thread
until the transport returns, while the caller receives a timeout and can apply
normal retry/fallback policy. This is the same ambiguity inherent in network
timeouts, but it bounds caller-visible latency and prevents process shutdown
from waiting on an abandoned attempt.

## Closeout Evidence

- Focused deadline, lifecycle, timeout-policy, and retry coverage passed: 31
  tests.
- The plan test gate passed 260 tests with shared cooldown/rate-limit state
  disabled for deterministic local execution.
- A deployed consumer run completed 20 turns and 40 structured DeepSeek calls.
  One stalled provider attempt hit this deadline, retried, and the run continued
  to completion without operator intervention.
- A fresh five-run consumer control later exercised the same deadline under
  concurrent provider load and recovered automatically.
- The broader repository suite was attempted but is not a valid closeout signal
  in this checkout: optional `data_contracts` and `prompt_eval` packages are
  absent, strict mypy reports existing repo-wide errors with installed mypy 2.3,
  and an unrelated concurrent SQLite lifecycle-logging test segfaulted during a
  full run. No failure implicated the changed deadline/retry paths.
