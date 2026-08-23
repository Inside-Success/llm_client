# Plan #355: Codex Intrinsic Event Custody

**Status:** In Progress
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

### Downstream audit correction (2026-08-23)

AC16's full-Codex harness audit found that completed-item projection is not
lossless enough for an experiment authority. It cannot distinguish a stream
that genuinely omitted an event from one where the shared parser ignored a
malformed, unknown, or non-completed envelope. Reconstructing JSONL from
`codex_events` in the consumer would create synthetic evidence.

The shared seam will therefore also expose
`codex_jsonl: list[str]`: every nonblank CLI stdout line, byte-for-byte after
Python's text decoding and in original order. `codex_events` remains the
normalized completed-item convenience projection. The new field is additive,
defaults empty on non-CLI routes, and does not claim provider attestation,
persistence, or semantic validity. AC16 will hash and persist this exact field,
then fail closed on malformed or unsupported envelopes.

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

- `docs/plans/supporting/355_work_graph.json`
- `llm_client/core/data_types.py`
- `llm_client/schemas.py`
- `llm_client/sdk/agents_codex.py`
- `tests/test_agents.py`
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
| `tests/test_agents.py` | `test_public_structured_call_retains_codex_completed_items` | the public structured API preserves the same completed-item receipt consumed by Agent Ecology 3 |
| `tests/test_boundary_schemas.py` | `test_codex_events_schema_is_additive_list` | the Pydantic public schema mirrors the additive list field |

### Existing Tests

| Test Pattern | Why |
|---|---|
| `tests/test_agents.py` | existing command, result, MCP, usage, and subscription semantics do not regress |
| `tests/test_boundary_schemas.py` | every public result field remains represented at the boundary |

## Acceptance Criteria

- [x] `LLMCallResult` and `LLMCallResultSchema` expose additive
      `codex_events: list[dict[str, Any]]` fields with empty-list defaults.
- [x] Direct Codex CLI calls retain every mapping-valued completed item in
      stream order.
- [x] Existing MCP `tool_calls` normalization is unchanged.
- [x] Focused tests, lint/type checks, required-reading gates, API generation,
      and diff hygiene pass.
- [ ] Agent Ecology 3's provider-free preflight observes its three intrinsic
      fixture types from this public field at the exact merged revision.
- [ ] Direct Codex CLI calls expose every nonblank stdout JSONL line verbatim
      and in order through additive `LLMCallResult.codex_jsonl`; process
      serialization and the boundary schema preserve it without reconstructing
      events.
- [ ] AC16 pins the accepted revision and proves malformed-line detection from
      the public exact-stream field rather than from a local subprocess parser.

## Reset Boundary

If the Codex CLI fixture shows completed intrinsic activity outside
`item.completed.item`, pause implementation and revise this plan from the
observed envelope. Do not broaden into persistence, streaming, or a generic
cross-provider event taxonomy without a demonstrated consumer requirement.

## Work Graph

The machine-consumed coordination record is
`docs/plans/supporting/355_work_graph.json`. `WU-355-01` owns the shared-client
contract and is ready. `WU-355-02` owns the Agent Ecology 3 adoption and remains
blocked until the shared unit is accepted on the canonical default branch.

## Shared-Unit Evidence (2026-08-12)

- Five new deterministic tests cover ordered completed-item custody, malformed
  and unsettled input, direct CLI result attachment, the public structured-call
  path used by Agent Ecology 3, and boundary-schema parity.
- The plan-scoped gate passed 161 tests across `tests/test_agents.py` and
  `tests/test_boundary_schemas.py`; the Luna/Terra route selection subset also
  passed. No provider call was made.
- The generated Markdown and HTML API references are in sync. Required-reading
  gates and `git diff --check` pass.
- Ruff and focused mypy retain the exact diagnostic counts present on `main`;
  neither reports a branch-only finding. The broad repository run produced
  2,081 passes, four skips, 12 deselections, and 16 unrelated baseline failures
  in optional `prompt_eval`, shared Instructor-cache ordering, doc-coupling
  fixtures, and hook subprocess PATH handling.
- The remaining acceptance item belongs to `WU-355-02`: after this shared unit
  merges, Agent Ecology 3 must bind the exact revision and rerun its
  provider-free preflight before any live Luna canary is considered.
