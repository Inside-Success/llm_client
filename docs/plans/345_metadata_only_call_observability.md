# Plan #345: Metadata-Only Call Observability

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Qualitative Coding public guest-analysis privacy repair

---

## Gap

**Current:** Structured calls always persist full prompts, parsed responses, call
snapshots, and dynamic error text in the normal call ledger. A public consumer
cannot retain cost/token telemetry without also retaining temporary source text.

**Target:** Add one typed, opt-in `metadata_only` policy for structured calls.
It preserves task, trace, model, usage, cost, latency, retry, execution-path,
schema, and error-class metadata while omitting prompts, responses, snapshots,
warnings, validation text, dynamic error text, and optional raw-response
artifacts. Existing callers retain full diagnostics by default.

**Why:** Public applications need truthful spend and lifecycle observability
without silently extending their source-data retention period.

---

## References Reviewed

- `CLAUDE.md` — shared-client, observability, planning, and fail-loud rules.
- `docs/adr/0007-observability-contract-boundary.md` — safe-by-default
  persistence and observability ownership.
- `docs/adr/0012-shared-data-plane-boundary.md` — metadata belongs in
  `llm_client`; raw application payloads do not.
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` — lifecycle
  metadata remains independent of call-content persistence.
- `docs/plans/110_provider-capabilities-opus-ban.md` and
  `docs/plans/336_typed_openrouter_route_policy.md` — typed call-policy and
  provider-routing boundaries.

---

## Files Affected

- `llm_client/execution/call_contracts.py`
- `llm_client/core/client.py`
- `llm_client/core/client_dispatch.py`
- `llm_client/execution/structured_runtime.py`
- `llm_client/io_log.py`
- `llm_client/__init__.py`
- `tests/test_io_log.py`
- `tests/test_client.py`
- `docs/API_REFERENCE.md` (generated)
- `docs/plans/CLAUDE.md`

---

## Plan

1. Add a frozen `ObservabilityContentPolicy` with `full` and `metadata_only`
   modes and expose it from the public package.
2. Carry the policy through sync and async structured-call paths without
   forwarding it to providers or including it in replay snapshots.
3. Redact content-bearing call-ledger fields and skip optional raw-response
   artifacts under `metadata_only`, while retaining bounded numeric and typed
   operational metadata.
4. Prove additive SQLite migration, JSONL/SQLite redaction, unchanged default
   behavior, and consumer integration.

---

## Required Tests

| Test | What It Verifies |
|---|---|
| metadata-only success call | telemetry persists while source and response sentinels do not |
| metadata-only failed call | error class persists while dynamic text and raw response do not |
| default full call | existing diagnostics remain unchanged |
| migrated SQLite schema | the content-persistence mode is queryable |
| QC integration test | public calls select metadata-only plus typed OpenRouter ZDR policy |

---

## Acceptance Criteria

- [ ] Policy misuse fails before provider dispatch.
- [ ] Metadata-only SQLite and JSONL rows contain no prompt, response, snapshot,
      warning, validation, or dynamic error content.
- [ ] Optional structured raw-response artifacts are not written.
- [ ] Usage, cost, trace, task, model, latency, retry, execution path, schema,
      and error class remain queryable.
- [ ] Existing calls remain full-fidelity by default.
- [ ] Focused tests, generated API reference, lint, and diff checks pass.

## Non-Goals

- Retrofitting or deleting historical call records.
- Changing stream, embedding, tool-call, or agent-SDK content policy.
- Replacing provider-side retention controls.
