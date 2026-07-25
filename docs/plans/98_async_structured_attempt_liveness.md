# Plan #98: Async structured-attempt liveness

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** DIGIMON Plan #111 bound-trace refresh

---

## Gap

**Current:** `LLM_CLIENT_TIMEOUT_POLICY=ban` intentionally removes a caller's
request timeout. `LLM_CLIENT_SAFETY_TIMEOUT` is then reported as the effective
300-second safety ceiling in lifecycle events, and provider kwargs receive that
value where supported. The async structured native-schema, Responses, and
Instructor paths nevertheless await the provider coroutine directly. A
provider/transport that does not honor its timeout can therefore remain pending
past the advertised ceiling. DIGIMON trace
`digimon.query.library_trace_gate.d011ea7f236d4f11b9313b817765eb1b`
demonstrated this: the third native-schema OpenRouter attempt remained on an
established socket for more than five minutes, with no response or terminal
attempt event, until the process was interrupted.

**Target:** Preserve two distinct contracts:

1. a **request timeout** is forwarded to the provider and remains governed by
   `LLM_CLIENT_TIMEOUT_POLICY`; and
2. an **async attempt safety ceiling** wraps each provider await in the client
   process and remains governed by `LLM_CLIENT_SAFETY_TIMEOUT`.

For cancellation-cooperative async provider transports, the client must request
cancellation at the safety ceiling even when the provider ignores its own
request timeout. Once cancellation completes, a safety timeout is retryable
under the existing retry policy and the public wrapper must emit one terminal
`failed` lifecycle event. The ceiling applies per provider attempt, not to the
entire logical call, so retry/backoff time is not silently reclassified as a
stalled provider. A coroutine that swallows cancellation cannot be hard-stopped
inside the same Python process; that case requires process isolation and is an
explicit non-claim of this slice.

**Why:** Reporting a deadline without enforcing it is false observability.
Repeated retries can occasionally avoid the symptom but cannot prove bounded
liveness. Filtering teardown output would hide the failure rather than repair
the missing control boundary.

## Requirements and boundaries

1. Keep request timeout, attempt safety ceiling, lifecycle stall inference, and
   batch item timeout as distinct concepts.
2. Enforce the safety ceiling in-process by issuing cancellation around each
   async provider await. Do not rely only on a provider SDK honoring `timeout=`
   and do not call cooperative cancellation a hard process kill.
3. Apply the same helper to native JSON Schema, Responses API, and Instructor
   provider-backed async structured paths. Agent-SDK calls retain their existing
   transport-specific hard-timeout contracts and are outside this slice.
4. Preserve existing retry/fallback policy. The safety exception must remain
   classifiable as transient; this plan does not add or remove an allowed retry.
5. Preserve `LLM_CLIENT_SAFETY_TIMEOUT=0` as the explicit operator-controlled
   disable switch. An implicit or malformed value must not disable the default.
6. Emit a non-empty error containing caller, model, and configured ceiling, and
   preserve it in the terminal lifecycle event.
7. Preserve provider-raised `TimeoutError` identity; only a client deadline that
   actually expires may be labeled as the async attempt safety ceiling.
8. Do not add a whole-logical-call timeout. That would change the semantics of
   retries, fallback, and backoff rather than isolate a non-returning provider
   attempt.
9. The synchronous structured path is not claimed process-cancellable by this
   slice. It retains the provider-level safety value; a hard sync cancellation
   boundary requires process isolation or a transport that cooperates with
   cancellation and must not be faked with an abandoned thread.

## Pre-make decisions

| Decision | Resolution | Reason |
|---|---|---|
| Safety scope | One provider attempt | Separates provider liveness from retry policy. |
| Enforcement owner | `llm_client` async execution layer | Provider timeouts are not a sufficient cancellation boundary. |
| Exception family | Standard timeout, wrapped by existing `LLMTransientError` boundary | Keeps current retry and caller compatibility while retaining the original timeout for lifecycle classification. |
| Sync parity | Explicitly out of scope | Python cannot safely terminate an arbitrary blocking sync SDK call in-process. |
| Threshold | Existing configurable `LLM_CLIENT_SAFETY_TIMEOUT` | No new hardcoded policy or app-local override. |

## References reviewed

- `llm_client/execution/timeout_policy.py` — request-policy and advertised safety ceiling.
- `llm_client/execution/call_lifecycle.py` — lifecycle timeout reporting and terminal event contract.
- `llm_client/execution/call_wrappers.py` — public async lifecycle finalization.
- `llm_client/execution/structured_runtime.py` — three unbounded provider-backed async structured awaits.
- `llm_client/execution/text_runtime.py` — existing process-side async provider wait pattern.
- `llm_client/execution/retry.py` — timeout retry classification.
- `tests/test_client_lifecycle.py`, `tests/test_timeout_policy.py` — current deterministic contract coverage.
- `docs/plans/21_runtime_durability_followups_from_grounded_research.md` — prior finite-timeout claim that did not prove this boundary.
- `docs/adr/0001-model-identity-v0.md` — requested/resolved model identity retained in timeout evidence.
- `docs/adr/0002-routing-config-precedence.md` — explicit timeout-policy fixtures avoid ambient-environment drift.
- `docs/adr/0003-warning-taxonomy.md` — terminal failures remain typed events rather than warnings.
- `docs/adr/0004-result-model-semantics-migration.md` — result identity remains unchanged.
- `docs/adr/0009-long-thinking-background-polling.md` — background polling keeps its separate long-call contract.
- `docs/adr/0010-cross-project-runtime-substrate.md` — shared execution and observability ownership.
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` — progress inference remains distinct from enforced liveness.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — lifecycle evidence remains truthful without changing call snapshots.
- DIGIMON `ISSUES.md` ISSUE-029 and Plan #111 progress — live downstream evidence.

## Files affected

- `llm_client/execution/timeout_policy.py` (shared async safety-await helper)
- `llm_client/execution/structured_runtime.py` (three provider-backed async call sites)
- `tests/test_timeout_policy.py` (helper positive/negative controls)
- `tests/test_client_lifecycle.py` (native-schema public-boundary negative control)
- `docs/plans/21_runtime_durability_followups_from_grounded_research.md` (correct overbroad prior claim)
- `docs/plans/98_async_structured_attempt_liveness.md` (this plan/evidence)
- `docs/plans/CLAUDE.md` (plan index)
- `docs/adr/0001`, `0002`, `0003`, `0004`, `0009`, `0010`, and `0014` (coupled verification contexts)
- DIGIMON Plan #111 / ISSUE-029 after the shared slice is verified

## Thin slice

1. Freeze a no-network coroutine that never completes and show the current
   helper/call path does not terminate at the configured client-side ceiling.
2. Add one shared await helper that applies the configured safety ceiling and
   raises a contextual timeout while preserving cancellation.
3. Route the three provider-backed async structured awaits through that helper.
4. Prove the native-schema public boundary under `TIMEOUT_POLICY=ban`: the
   provider coroutine is cancelled, the public error retains the safety cause,
   and lifecycle history ends in `failed` rather than remaining active.
5. Run focused timeout/lifecycle/structured tests, type/lint checks, then use the
   branch as an isolated dependency to regenerate the blocked DIGIMON trace.
6. Update evidence grades from observed results; commit and push without
   merging the shared default branch implicitly.

## Required Tests

| Test File | Test Function | Positive side / negative control |
|---|---|---|
| `tests/test_timeout_policy.py` | `test_async_safety_ceiling_returns_completed_awaitable` | completed awaitable returns unchanged |
| `tests/test_timeout_policy.py` | `test_async_safety_ceiling_cancels_nonreturning_awaitable` | non-returning awaitable is cancelled and raises contextual timeout |
| `tests/test_timeout_policy.py` | `test_provider_timeout_is_not_relabelled_as_safety_timeout` | a provider-raised timeout retains its own identity and message |
| `tests/test_timeout_policy.py` | `test_malformed_safety_timeout_uses_default_and_logs` | invalid configuration retains the finite default and fails visibly |
| `tests/test_timeout_policy.py` | `test_disabled_async_safety_ceiling_allows_completion` | explicit `0` leaves waiting to the caller without silently cancelling |
| `tests/test_timeout_policy.py` | `test_normalize_timeout_ban_appends_warning_and_zeroes_timeout` | request timeout remains normalized to zero independently of safety |
| `tests/test_client_lifecycle.py` | `test_async_structured_safety_timeout_cancels_provider_and_emits_failed_lifecycle` | hung native-schema provider is cancelled; lifecycle is `started -> failed` with `TimeoutError` |
| downstream command | DIGIMON bound trace | invocation imports this worktree revision; canonical dependency is not silently claimed fixed before merge |

## Acceptance Criteria

### Evidence grades

| ID | Criterion | Required evidence | Baseline |
|---|---|---|---|
| L98-1 | Request timeout and safety ceiling have separate executable contracts. | source + timeout-policy tests | D/doc |
| L98-2 | Every provider-backed async structured attempt uses the shared process-side safety await. | source scan + branch tests for helper/native boundary | F/missing |
| L98-3 | A cancellation-cooperative provider coroutine is cancelled when the configured ceiling expires. | deterministic async negative control | B/live hang proves current gap |
| L98-4 | Timeout reaches public callers as a transient error with the original timeout retained. | public-boundary test | F/missing |
| L98-5 | Lifecycle history terminates with a truthful failed event and no blank error. | isolated DB readback | F/missing |
| L98-6 | Retry/backoff semantics are unchanged because the ceiling is per attempt, not per logical call. | source review + existing retry suite | D/doc |
| L98-7 | Prior finite-timeout documentation is corrected to its proven scope. | plan/doc diff | F/wrong current claim |
| L98-8 | The DIGIMON trace lane no longer waits indefinitely under timeout ban when bound to this runtime. | live downstream run with exact runtime revision | F/not run |

Baseline coverage: A=0, B=1, C=0, D=2, F=5. No completion claim or hard
downstream gate is enabled until the negative control first demonstrates the
old failure and then passes on the implementation.

## Slice 1 progress — 2026-07-12

The deterministic public-boundary negative control first failed on the old
runtime: its 1.5-second harness backstop cancelled the still-pending provider
task, while no `LLMTransientError` or terminal client lifecycle event existed.
That is the bounded proxy for the live five-minute DIGIMON hang; the external
test deadline is not counted as the implementation.

The shared `_await_with_safety_ceiling` now creates one task per provider
attempt, waits for the configured ceiling, requests cancellation when the
deadline expires, and propagates external cancellation. A completed provider
task is awaited directly, so a provider-raised `TimeoutError` retains its own
message instead of being falsely labeled as a safety timeout. Native schema,
Responses API, and Instructor call sites all use this seam.

Observed branch controls:

- `tests/test_timeout_policy.py`, `tests/test_client_lifecycle.py`, and
  `tests/test_structured_attempts.py` → 27 passed.
- `python scripts/meta/check_plan_tests.py --plan 98` → 20 passed.
- `tests/test_client.py -k structured` → 19 passed, 224 deselected.
- The three provider-path parameters each produced `started -> failed`, retained
  an original `TimeoutError`, cancelled the provider fixture, and recorded a
  non-empty terminal lifecycle error.
- Ruff passed on all changed Python files.
- Focused mypy with dependency imports skipped passed on both changed runtime
  files. The repo-wide/transitive mypy invocation remains red on its existing
  baseline (181 errors); this slice removed the two errors in the touched
  timeout module and three local errors in the touched structured module rather
  than claiming unrelated type debt resolved.
- Plan validation and documentation coupling checks pass.

Current evidence: L98-1=A, L98-2=A, L98-3=A for cancellation-cooperative
awaitables, L98-4=A, L98-5=A, L98-6=B, L98-7=A, L98-8=F. Completion remains
blocked on the downstream DIGIMON bound trace and on landing this isolated
shared-runtime branch; sync hard termination remains an explicit non-claim.

## Slice 2 progress — 2026-07-13

DIGIMON loaded this worktree revision through an explicit `PYTHONPATH`
binding, then regenerated both maintained live query gates without an
unbounded provider wait:

- `digimon_e2e_v0` passed with no failed checks, a passing corruption negative
  control, and trace IDs
  `digimon.query.dynamic_trace_gate.488db9bef33b4bb6bff18290b2b0cc0a.single`
  and
  `digimon.query.dynamic_trace_gate.488db9bef33b4bb6bff18290b2b0cc0a.agentic`.
- `digimon_dynamic_query` passed with no failed checks, a passing corruption
  negative control, and trace IDs
  `digimon.query.dynamic_trace_gate.8100097d697d4f03bb45df61a3f2869b.single`
  and
  `digimon.query.dynamic_trace_gate.8100097d697d4f03bb45df61a3f2869b.agentic`.
- The E2E run retained a fenced-JSON schema failure in the attempt history and
  recovered on the configured retry. This is intentional observability: the
  liveness boundary bounds a provider await and does not suppress a real
  structured-output failure.
- The downstream commands imported
  `llm_client/execution/timeout_policy.py` from this worktree; the safety helper
  was present at runtime. The first pre-fix E2E attempt had remained pending
  beyond five minutes in answer synthesis, while the bound run completed.

The focused suite now reports 28 passing timeout/lifecycle/structured tests,
including an explicit proof that caller cancellation propagates unchanged, and
the Plan #98 required-test runner reports 21 passing tests. Current evidence is
L98-1=A, L98-2=A, L98-3=A for cancellation-cooperative awaitables, L98-4=A,
L98-5=A, L98-6=B, L98-7=A, and L98-8=A. The documented sync and
cancellation-swallowing transport non-claims remain unchanged.

The sanctioned completion wrapper was also run without duplicating paid E2E
calls. It did not change this plan's status because its unsharded 1,559-test
unit command exceeded the wrapper's fixed 300-second ceiling. A clean detached
`origin/main` worktree reproduced the slow quota/cooldown control independently
of this branch, and the broad run also exposed two existing failures caused by
the environment's missing optional `prompt_eval` checkout. Neither path imports
or exercises the Plan #98 structured-attempt changes. The branch is therefore
ready for review and downstream use, but the plan remains formally In Progress
until the shared completion baseline or its fixed timeout is repaired; no
`--force` status override was used.

### Completion reconciliation — 2026-07-25

The optional dependency gap is resolved in the canonical repository
environment. The Plan #98 gate passes 25 tests, the retained downstream
DIGIMON traces satisfy L98-8, and current personal `main` passes its complete
suite (`1,930 passed`, `3 skipped`, `12 deselected`). The old completion
wrapper's fixed 300-second ceiling remains tooling debt—the observed full suite
took 351.91 seconds—but no longer keeps the implemented and downstream-proven
liveness capability falsely active.

## Failure handling

| Failure | Action |
|---|---|
| cancellation does not reach or terminate the provider coroutine | block; inspect SDK task ownership and consider process isolation rather than adding retries or claiming a hard deadline |
| timeout is swallowed/reclassified as success | block; preserve the exception through retry/fallback and public wrapper |
| lifecycle remains active after timeout | block; fix terminal wrapper cleanup before downstream verification |
| full structured suite regresses | revert the narrow call-site slice and isolate the affected provider path |
| sync path still lacks a hard process boundary | retain explicit concern; do not claim sync parity |
| SSL teardown remains after bounded cancellation | keep as a separate transport-shutdown issue; do not conflate with liveness |
