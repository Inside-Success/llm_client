# Plan #334: Empty Structured Response Observability

**Status:** Implemented on main; governed downstream live trace pending
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #122 client deadline classification
**Blocks:** Specific diagnosis of empty structured responses

---

## Gap

**Current:** A live Process Tracing trace received a native-schema response and
then failed with `Empty content from LLM`. The diagnostic records only the later
`ValueError`, losing typed completion metadata available on the response object.

**Target:** Retain a strict allowlisted `response_outcome` (`empty_content`)
and any existing typed response IDs, without raw content, headers, tool calls,
or reasoning text.

**Why:** This distinguishes a received empty response from a transport failure
without claiming provider fault.

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.

- `llm_client/execution/structured_runtime.py:519-630,1488-1502,2532-2546` -
  diagnostic boundary and sync/async native response handling.
- `llm_client/observability/attempt_diagnostics.py` and `llm_client/io_log.py`
  - strict envelope and additive SQLite persistence.
- `docs/plans/121_attempt_diagnostic_envelope.md` and `AGENTS.md` - privacy,
  observability, and verification constraints.
- `docs/adr/DECISIONS.md#0001-model-identity-v0`
- `docs/adr/DECISIONS.md#0002-routing-config-precedence`
- `docs/adr/DECISIONS.md#0003-warning-taxonomy`
- `docs/adr/DECISIONS.md#0004-result-model-semantics-migration`
- `docs/adr/DECISIONS.md#0007-observability-contract-boundary`
- `docs/adr/DECISIONS.md#0009-long-thinking-background-polling`
- `docs/adr/DECISIONS.md#0010-cross-project-runtime-substrate`
- `docs/adr/DECISIONS.md#0012-shared-data-plane-boundary`
- `docs/adr/DECISIONS.md#0013-stream-lifecycle-heartbeat-observability`
- `docs/adr/DECISIONS.md#0014-call-replay-and-divergence-diagnosis-boundary`
- `docs/adr/DECISIONS.md#0016-provider-capability-and-vendor-telemetry-boundary`
- `docs/plans/COMPLETED_PLANS.md#117_explicit_reasoning_policy`

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.

- `llm_client/observability/attempt_diagnostics.py`
- `llm_client/io_log.py`
- `llm_client/execution/structured_runtime.py`
- `tests/test_attempt_diagnostics.py`

---

## Plan

### Steps

1. Add an additive, constrained response-outcome diagnostic field and migration.
2. Capture it only after a response object is observed and its content is empty.
3. Prove sync and async readback plus a raw-content negative control.
4. Run focused tests and a governed downstream call.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_attempt_diagnostics.py` | `test_empty_response_preserves_typed_outcome` | Empty response is distinct from transport failure. |
| `tests/test_attempt_diagnostics.py` | `test_response_outcome_rejects_raw_content` | No raw content can enter the ledger. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_attempt_diagnostics.py` | Existing privacy and attribution controls remain intact. |

---

## Acceptance Criteria

- [x] Empty response records `response_outcome=empty_content` with client-only attribution.
- [x] No body, header map, prompt, tool call, or reasoning content is retained.
- [x] Existing transport and timeout outcomes remain unchanged.
- [ ] Focused tests and a governed live trace are retained.

---

## Notes

The response object proves only that the client received an object, not that a
named gateway or provider is at fault. The response outcome is therefore a
client-observed fact. No raw artifact is created for empty content.
