# ADR 0007: Observability Contract Boundary

Status: Accepted  
Last verified: 2026-07-14
Verification context: canonical typed attempt, selected-attempt receipt, opt-in exact raw-artifact, v3 replay-policy, and tool-call
models live under `observability/`; `io_log` persists effective
retry/fallback/cache/budget state, unsupported or malformed replay
reconstruction fails loud, and v3 replay requires fresh budget authority.
Raw-artifact reads reject malformed, expired, or substituted paths, and cleanup remains an
importable observability operation after collection is disabled. Focused
persistence, selected-attempt, replay, and tool-call controls pass.
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

Last verified: 2026-07-14 (Plan 97 Slice 3 transport-attempt lifecycle).

Plan 101 adds trusted-process runtime receipts; it does not claim provider
attestation, source authentication, signatures, or hostile-process security.
