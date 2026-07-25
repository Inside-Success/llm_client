# Budget-Complete Call Snapshot V3

**Date:** 2026-07-14
**Question:** How should `llm_client` retain the effective request budget without
changing historical replay semantics or silently reusing an old authorization?

## Sources Consulted

- `llm_client/observability/replay.py`
- `llm_client/execution/text_runtime.py`
- `llm_client/execution/structured_runtime.py`
- `tests/test_observability_replay.py`
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md`
- DoDAF Plan 24 dependency observation at exact shared revision `d74b8ea`
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/)

## Observations

1. Every public text and structured runtime requires and checks `max_budget`
   before dispatch, but `build_call_snapshot()` does not accept or retain it.
2. Snapshot v2 is a closed `extra="forbid"` envelope. Adding a required field
   in place would make historical v2 bytes ambiguous.
3. V2 fingerprints the complete versioned envelope. V1 retains historical
   request-only fingerprint behavior.
4. Replay currently accepts v1/v2 and supplies a default `$0` fresh budget. A
   v3 replay must not inherit the captured budget because accumulated trace cost
   and operator authorization belong to the new execution.
5. RFC 8785 reinforces that fingerprint inputs need invariant serialization;
   the existing sorted compact JSON representation already provides the needed
   bounded behavior for these typed JSON values. No new canonicalization library
   is justified for this additive field.
6. W3C PROV distinguishes a derived entity from its source. The replay is a new
   call derived from a captured request, not a continuation of its original
   spend authorization.
7. The active Plan 97 worktree is clean at unmerged commit `d74b8ea`. A child
   branch based on that exact commit preserves its structured-attempt repair.

## Decision

Introduce snapshot v3. Add required finite nonnegative
`request.control.max_budget` to the closed v3 policy. New snapshots are v3 and
their fingerprints cover the entire envelope. Historical v1 and v2 reads and
fingerprints remain unchanged. V3 replay requires the caller to supply a fresh
explicit finite nonnegative budget; it never copies the captured value into the
new dispatch.

Use the existing builder and runtime seams. Do not add a side receipt, database
migration, provider call, UI, or compatibility fallback.

## Failure Readout

- Missing or malformed captured v3 budget: reject before replay dispatch.
- Missing fresh v3 replay budget: reject before replay dispatch.
- V1/v2 historical fixture changes: reject the implementation.
- Any text/structured sync/async path omits the effective budget: reject the
  implementation.
- A captured-budget mutation leaves the fingerprint unchanged: reject the
  implementation.
