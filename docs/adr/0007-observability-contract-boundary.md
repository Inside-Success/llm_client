# ADR 0007: Observability Contract Boundary

Status: Accepted  
Last verified: 2026-07-23
Verification context: Provider-reported prompt and completion token details are
preserved as bounded numeric metadata, with reasoning/cache counts queryable in
SQLite. Hidden reasoning content and arbitrary provider payload fields remain
outside the observability store.
Date: 2026-02-23

## Context

Observability logic was historically mixed into core call paths, and `io_log.py`
served both as implementation and public API surface. As the codebase split into
`llm_client/observability/*` modules, we needed a stable contract for what is
persisted, how compatibility is preserved, and where behavior should evolve.

## Decision

1. Canonical observability implementation lives in `llm_client/observability/*`.
2. `llm_client/io_log.py` remains a compatibility facade for existing imports.
3. Default persistence behavior remains safe-by-default:
   - metadata-first logging,
   - no requirement to persist full raw content in default paths.
4. Warning and routing-related diagnostics emitted into observability surfaces
   must remain aligned with the warning taxonomy contract in ADR 0003.
5. Any breaking changes to observability payload shape or sink behavior require
   a dedicated ADR update.
6. The canonical tool-call surface exposes two explicit policies:
   - `log_tool_call` preserves compatibility best-effort behavior,
   - `log_tool_call_strict` is for pipeline-critical evidence and fails when
   logging is disabled, the trace id is blank, or either configured sink fails.
7. LLM usage accounting preserves bounded provider-reported numeric token
   details when available. Aggregate counts remain authoritative as reported;
   missing detail fields are not inferred, and reasoning content is not stored.

## Consequences

Positive:
1. Clear boundary between core execution and observability concerns.
2. Preserved compatibility for existing `io_log` consumers.
3. Better maintainability for query/experiment/reporting evolution.

Negative:
1. Transitional complexity while both compatibility facade and canonical modules exist.
2. Requires discipline to keep facade behavior aligned with canonical modules.

## Testing Contract

1. Compatibility tests must cover `io_log` delegated behavior.
2. Observability tests must verify default-safe persistence behavior.
3. Warning/diagnostic emission must remain category-consistent with ADR 0003.
4. Strict persistence tests must cover both sinks, disabled logging, and null or
   blank trace identifiers.
5. Native-schema attempt tests must cover `started` before provider invocation,
   typed pre-response failure, and retry-kernel recovery disposition. Attempt
   events exclude exception messages and provider bodies.
6. Usage-detail tests must cover Completion and Responses normalization, fresh
   and migrated SQLite schemas, JSONL import, query round-trip, and
   content-bearing negative controls.

Last verified: 2026-07-14 (Plan 97 Slice 3 transport-attempt lifecycle).

## 2026-07-25 Amendment: Privacy-Bounded Attempt Diagnostics

Plan 121 adds an additive `attempt_diagnostics` child ledger. It may retain
typed status/error identifiers, request-correlation identifiers, timeout kind,
exception class names/fingerprint, and a bounded `sanitized_summary` only after
deterministic redaction rejects credential, authorization, prompt, and raw-body
patterns. Raw exception messages, provider bodies, prompts, and headers remain
outside SQLite and require a separately authorized artifact reference. A
diagnostic records client-observed origin and attribution limits; it cannot
claim provider fault without typed provider/gateway response evidence.

Plan 101 adds trusted-process runtime receipts; it does not claim provider
attestation, source authentication, signatures, or hostile-process security.

## 2026-07-25 Amendment: Durable Budget Reservations

Plan 334 adds additive `budget_scopes` and `budget_reservations` metadata to
the SQLite observability store. They retain trace identifiers, normalized
micro-USD amounts, ownership IDs, and lifecycle timestamps only. They must not
retain prompts, responses, provider payloads, credentials, or exception text.
The canonical transaction logic lives in
`llm_client/observability/budget_reservations.py`; `io_log.py` owns only schema
creation and compatibility access to the shared SQLite connection.

## 2026-07-25 Amendment: Synchronized Sink Shutdown

The compatibility facade owns synchronized closure of its shared SQLite
connection. Shutdown waits behind the same write lock used by persistence and
then takes the connection lock in the normal write-path order. Tests and
maintenance commands must call `io_log.close()` rather than closing
`_db_conn` directly; this prevents lifecycle heartbeat writers from operating
on a connection closed concurrently by teardown.
