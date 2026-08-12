# Plan #350: Tool Response Custody

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Agent Ecology 3 provider qualification and prescription ablation

---

## Gap

**Current:** Full-content `llm_calls` rows retain rendered messages and response
text, but retain only the count of response tool calls. For a tool-only result,
the response field is empty and the exact `LLMCallResult.tool_calls` payload is
lost after the caller exits. A trace ID and receipt therefore cannot reopen the
model action that the application actually parsed.

**Target:** Under the existing `full` content-persistence policy, retain the
exact serializable response tool-call payload in JSONL and SQLite and expose it
through exact-call readback. Under `metadata_only`, retain no payload and keep
only the existing count. Existing text-response and receipt semantics remain
unchanged.

**Why:** Agent Ecology 3's first prescription ablation linked every syscall to
a shared-client receipt but could not satisfy its replay evidence contract for
74 tool-only calls. The shared client owns this transport/result boundary; an
application-local duplicate would create a second custody authority.

---

## Boundaries

- This stores the normalized, lossless `LLMCallResult.tool_calls` list seen by
  the caller, including call ID, function name, and argument string. It does not
  claim to preserve a provider-specific SDK object or provider attestation.
- The payload follows `ObservabilityContentPolicy`: `full` retains it and
  `metadata_only` omits it.
- The existing `response` text column and `response_sha256` receipt field do not
  change meaning.
- Migration is additive; old rows read back with `response_tool_calls=null`.
- No provider call, route change, package publication, or historical-row
  retrofit is in scope.

## References Reviewed

- `llm_client/io_log.py:390-540,790-820,1280-1350,1850-1920` — result extraction,
  content policy, SQLite schema/migration, and terminal-row persistence.
- `llm_client/execution/completion_runtime.py:125-195` — extraction of the public
  result's tool-call payload from provider responses.
- `llm_client/observability/query.py:24-100` — canonical call receipts.
- `llm_client/observability/replay.py:645-690` — exact call-record readback.
- `docs/plans/97_lossless-structured-output-attempt-observability.md` and
  `docs/plans/102_selected_raw_structured_content.md` — metadata-first and
  opt-in raw-artifact boundaries for structured output.
- `docs/plans/345_metadata_only_call_observability.md` — content-redaction
  authority that must also govern response tool calls.

## Files Affected

- `llm_client/io_log.py`
- `llm_client/observability/query.py`
- `llm_client/observability/replay.py`
- `tests/test_io_log.py`
- `tests/test_observability_replay.py`
- `docs/plans/350_tool_response_custody.md`
- `docs/plans/CLAUDE.md`

## Plan

1. Add failing full-content, metadata-only, migration, and exact-readback tests.
2. Capture a JSON-safe copy of `LLMCallResult.tool_calls` at the existing
   terminal logging boundary.
3. Add an additive nullable SQLite column and JSONL field.
4. Decode the field through exact-call replay without changing old-row behavior.
5. Run focused tests, the full suite, type/lint checks, and plan closeout.

## Required Tests

- `tests/test_io_log.py`
- `tests/test_observability_replay.py`
- `tests/test_call_receipts.py`

| Test | What it proves |
|---|---|
| full-content tool-only result | JSONL and SQLite retain the exact caller-visible tool-call payload despite empty response text |
| metadata-only tool result | tool payload and arguments are absent while `n_tool_calls` remains |
| old database migration | nullable column is added without rewriting prior rows |
| exact call readback | `get_call_record(call_id)` decodes the retained payload and returns `None` for old/redacted rows |
| text-only compatibility | response text and receipt hash semantics are unchanged |

## Acceptance Criteria

- [ ] Full-content tool calls are reopenable by exact call ID.
- [ ] Metadata-only calls do not retain tool names, IDs, or arguments.
- [ ] Existing databases migrate additively and old rows remain readable.
- [ ] The public result payload is preserved without claiming provider-raw
      object custody.
- [ ] Focused and full checks pass.

## Failure Handling

Serialization uses the same best-effort string conversion as other full-content
observability fields; logging remains non-fatal by its existing contract. A
missing or malformed stored JSON value fails exact readback rather than silently
returning a partial list. Metadata-only mode deliberately returns `None`.
