# Plan #355: Codex Intrinsic Event Custody

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Agent Ecology 3 Plan #10 Luna Medium recovery gate

---

## Gap

**Observed:** The direct Codex CLI adapter parses `item.completed` JSONL events,
but the public `LLMCallResult` retains only normalized MCP calls. Completed
intrinsic items such as `command_execution`, `file_change`, and `web_search`
disappear before the caller receives the settled result. A read-only downstream
consumer therefore cannot prove from the public receipt that Codex avoided its
intrinsic execution surfaces.

**Target:** Add an optional, transport-specific `codex_events` list to
`LLMCallResult`. For direct Codex CLI calls, populate it with JSON-safe copies of
every mapping-valued `item` from each valid `item.completed` event, in stream
order. Other routes return the additive default empty list. Keep the existing
normalized `tool_calls` contract unchanged.

**Why:** Agent Ecology 3's Luna MVP intentionally uses native structured output
instead of MCP, an empty working directory, and a read-only sandbox. Its
fail-closed action boundary still needs caller-visible evidence that the model
did not execute command, file, web, or MCP actions. The shared client owns the
transport/result seam; an application-local parser would create competing
custody.

## Bounded Design

- **Outcome:** A caller can inspect one successful Codex CLI result and
  deterministically enumerate every completed Codex item exposed by that CLI
  JSONL stream.
- **Canonical example:** A stream containing completed
  `command_execution`, `file_change`, `web_search`, and `mcp_tool_call` items
  produces four ordered `codex_events`; the existing `tool_calls` projection
  still contains only the MCP call.
- **Capability disposition:** Extend the existing public `LLMCallResult` seam.
  Do not add MCP, a callback, an AE3-specific type, or a second parser in the
  consumer.
- **Compatibility:** The field is additive with `default_factory=list`, is
  mirrored by `LLMCallResultSchema`, and remains empty for non-Codex and
  provider paths that do not expose Codex exec JSONL.
- **Failure behavior:** Blank lines, malformed JSON, non-mapping events,
  non-completed event envelopes, and non-mapping `item` values are ignored.
  Valid completed item mappings are copied rather than shared by reference.
- **Non-claims:** This field is normalized client custody of CLI output, not
  provider attestation, persistence/replay custody, live-stream observability,
  sandbox enforcement, or proof that a future unknown Codex item type is safe.

## References Reviewed

- `llm_client/core/data_types.py` — canonical public result dataclass.
- `llm_client/schemas.py` — Pydantic mirror used by the boundary registry.
- `llm_client/sdk/agents_codex.py` — Codex CLI JSONL parsing, MCP projection,
  and result construction.
- `docs/plans/42_codex_cli_mcp_parity.md` — existing MCP result projection.
- `docs/plans/350_tool_response_custody.md` — shared ownership and content
  custody precedent.
- Agent Ecology 3 Plan #10 and its retained provider-free preflight at
  `docs/evaluations/evidence/plan10_luna_recovery_gate/` — named consumer and
  reproduced blocker.

## Files Affected

- `llm_client/core/data_types.py`
- `llm_client/schemas.py`
- `llm_client/sdk/agents_codex.py`
- `tests/test_agents_codex_cli.py`
- `tests/test_boundary_schemas.py`
- generated `docs/API_REFERENCE.md`
- generated `docs/API_REFERENCE.html`
- `docs/plans/355_codex_intrinsic_event_custody.md`
- `docs/plans/CLAUDE.md`

## Plan

1. Add failing public-result, extraction, ordering, malformed-input, and schema
   mirror tests.
2. Add the additive `codex_events` dataclass and schema fields.
3. Extract completed item mappings once from Codex CLI stdout and attach them
   to the settled result without changing MCP normalization.
4. Regenerate the API reference and run the focused contract checks.
5. After merge, update Agent Ecology 3 to the exact shared revision and rerun
   its provider-free preflight. The separate one-call Luna canary remains an
   explicit authorization boundary.

## Required Tests

### New Tests

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_agents.py` | `test_extract_codex_cli_completed_items_retains_intrinsic_and_mcp_events` | all completed items remain ordered while MCP normalization stays separate |
| `tests/test_agents.py` | `test_extract_codex_cli_completed_items_ignores_malformed_and_unsettled_events` | invalid or incomplete envelopes do not create false completion evidence |
| `tests/test_agents.py` | `test_call_codex_via_cli_exposes_completed_items_on_public_result` | direct CLI results expose completed items through `codex_events` |
| `tests/test_boundary_schemas.py` | `test_codex_events_schema_is_additive_list` | the Pydantic public schema mirrors the additive list field |

### Existing Tests

| Test Pattern | Why |
|---|---|
| `tests/test_agents.py::TestCodexFallback` | existing command, result, MCP, usage, and subscription semantics do not regress |
| `tests/test_boundary_schemas.py` | every public result field remains represented at the boundary |

## Acceptance Criteria

- [ ] `LLMCallResult` and `LLMCallResultSchema` expose additive
      `codex_events: list[dict[str, Any]]` fields with empty-list defaults.
- [ ] Direct Codex CLI calls retain every mapping-valued completed item in
      stream order.
- [ ] Existing MCP `tool_calls` normalization is unchanged.
- [ ] Focused tests, lint/type checks, required-reading gates, API generation,
      and diff hygiene pass.
- [ ] Agent Ecology 3's provider-free preflight observes its three intrinsic
      fixture types from this public field at the exact merged revision.

## Reset Boundary

If the Codex CLI fixture shows completed intrinsic activity outside
`item.completed.item`, pause implementation and revise this plan from the
observed envelope. Do not broaden into persistence, streaming, or a generic
cross-provider event taxonomy without a demonstrated consumer requirement.
