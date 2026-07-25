# Plan #122: Client Attempt Deadline Classification

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #121 merged diagnostics contract
**Blocks:** Accurate cross-project timeout attribution

---

## Gap

**Current:** Plan 121 records a structured call that reaches the runtime's
documented `structured provider attempt exceeded <n>s client deadline` as
`timeout_kind="unknown"`. That loses a local fact already known at the
execution boundary and makes a bounded client deadline indistinguishable from
an unclassified transport timeout.

**Target:** Preserve `client_attempt_deadline` as a distinct typed timeout kind
when and only when the stable client deadline message is observed. Retain
`unknown` for every other `TimeoutError`; do not infer provider fault.

**Why:** Operators need to distinguish an intentional local deadline from
missing provider evidence before changing a model, retry policy, or timeout.

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.

- `llm_client/execution/structured_runtime.py:198-232,519-579` - stable
  client-deadline message and structured failure diagnostic capture.
- `llm_client/observability/attempt_diagnostics.py:43-85` - typed retained
  timeout taxonomy.
- `tests/test_attempt_diagnostics.py:190-225` - existing timeout and
  attribution controls.
- `docs/adr/0001-model-identity-v0.md` and
  `docs/adr/0004-result-model-semantics-migration.md` - requested and resolved
  model identity remains additive and unguessed.
- `docs/adr/0002-routing-config-precedence.md` and
  `docs/plans/117_explicit_reasoning_policy.md` - route and timeout policy are
  explicit runtime inputs rather than ambient inference.
- `docs/adr/0003-warning-taxonomy.md` - a known client deadline is an
  observability fact, not a provider-blame warning.
- `docs/adr/0007-observability-contract-boundary.md`,
  `docs/adr/0012-shared-data-plane-boundary.md`, and
  `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` - metadata-only
  retention and lifecycle semantics.
- `docs/adr/0009-long-thinking-background-polling.md`,
  `docs/adr/0010-cross-project-runtime-substrate.md`,
  `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`, and
  `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` - this
  is a reusable client-side timeout fact, distinct from background polling,
  replay, provider telemetry, and vendor attribution.
- `docs/plans/121_attempt_diagnostic_envelope.md` - prior diagnostic contract.
- `CLAUDE.md` - repository conventions and required verification.

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.

- `llm_client/observability/attempt_diagnostics.py` (modify)
- `llm_client/execution/structured_runtime.py` (modify)
- `tests/test_attempt_diagnostics.py` (modify)
- `docs/plans/CLAUDE.md` and this plan (modify)

---

## Plan

### Steps

1. Add the narrow `client_attempt_deadline` timeout-kind literal.
2. Classify only `_deadline_message()`-shaped timeout failures as that literal.
3. Add positive and negative focused tests.
4. Run plan tests, type/lint checks, then verify a governed downstream trace
   exposes the classification without widening persisted content.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_attempt_diagnostics.py` | `test_runtime_client_attempt_deadline_is_classified` | Stable local deadline receives the explicit client label. |
| `tests/test_attempt_diagnostics.py` | `test_runtime_unknown_timeout_remains_unknown` | Arbitrary timeout text does not gain an unsupported classification. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_attempt_diagnostics.py` | Existing diagnostic persistence and attribution remain intact. |

---

## Acceptance Criteria

- [ ] Stable deadline produces `client_attempt_deadline`.
- [ ] Unrecognized timeout remains `unknown`.
- [ ] No prompt, response, credential, or provider-body content is added.
- [ ] Focused tests, lint, and type checks pass; known unrelated broad-suite
  debt is reported rather than hidden.

---

## Notes

The label intentionally names a client-observed execution deadline, not a
provider request timeout or provider failure. It is additive and backwards
compatible for retained rows. The Process Tracing live trace is the downstream
acceptance artifact; it must be queried with its concrete child trace ID.
