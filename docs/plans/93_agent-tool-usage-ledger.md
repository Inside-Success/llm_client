# Plan #93: Agent tool-usage ledger

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Project-meta Plan #213 reporting and comparative tool-selection evaluation

---

## Gap

**Current:** Direct libraries can emit `ToolCallResult`, but agent clients do
not populate that surface for MCP calls. Historical Codex and Claude JSONL
transcripts contain structured call events, while raw string counts overcount
tool definitions and mentions.

**Target:** A generic, typed transcript importer writes a content-free,
idempotent SQLite ledger and exposes import/report commands through
`python -m llm_client tool-usage`.

**Why:** Tool and policy adoption cannot be evaluated from configuration or
string mentions. The system needs durable evidence of actual calls without
copying sensitive prompts, arguments, outputs, or filesystem paths.

## References Reviewed

- `CLAUDE.md` and subtree instruction files — repository rules.
- `docs/API_REFERENCE.md` and `scripts/meta/generate_api_reference.py` — public API docs contract.
- `docs/adr/0007-observability-contract-boundary.md` — metadata-first canonical observability boundary.
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` — truthful lifecycle semantics.
- `docs/adr/0003-warning-taxonomy.md` — stable operational warning semantics.
- `docs/adr/0010-cross-project-runtime-substrate.md` — shared observability ownership.
- `docs/adr/0012-shared-data-plane-boundary.md` — metadata belongs here; raw payloads do not.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — distinguish client-observed truth from inference.
- `llm_client/observability/tool_calls.py` — direct runtime tool-call contract.
- `llm_client/io_log.py` — existing SQLite conventions.
- `llm_client/cli/tools.py` and `llm_client/cli/common.py` — reporting/CLI conventions.
- Structured Codex and Claude JSONL event shapes, inspected without retaining content.
- `project-meta/docs/plans/213_codebase-memory-routing-and-usage-observability.md` — consumer policy contract.

## Files Affected

- `llm_client/observability/agent_tool_usage.py` (create)
- `llm_client/observability/__init__.py` (modify)
- `llm_client/cli/tool_usage.py` (create)
- `llm_client/__main__.py` (modify)
- `Makefile` (modify)
- `tests/test_agent_tool_usage.py` (create)
- `tests/test_cli_smoke.py` (modify)
- `scripts/meta/generate_api_reference.py` (modify — deterministic check-mode repair)
- `tests/test_api_reference_generation.py` (modify)
- `Makefile` (modify)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate)
- `docs/adr/0003-warning-taxonomy.md` (re-verify unchanged warning boundary)
- `docs/adr/0007-observability-contract-boundary.md` (update verification context)
- `docs/adr/0010-cross-project-runtime-substrate.md` (update verification context)
- `docs/adr/0012-shared-data-plane-boundary.md` (update verification context)
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` (re-verify unchanged stream boundary)
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` (update verification context)
- this plan and `docs/plans/CLAUDE.md`

## Plan

1. Define typed normalized event, import summary, and report contracts.
2. Parse structured Codex response-item/MCP-end and Claude tool-use/result events.
3. Persist only normalized metadata and hashes in a dedicated SQLite table.
4. Add idempotent import and aggregate report APIs.
5. Add thin CLI/Make surfaces.
6. Prove positive formats, negative controls, privacy, idempotency, and reports.

## Required Tests

| Test | What it verifies |
|------|------------------|
| old Codex fixture | fully qualified function call/output is counted once |
| current Codex fixture | MCP call-end server/tool event records outcome and duration |
| Claude fixture | tool-use/result correlation and explicit error status |
| definition/mention negative control | repeated names without structured calls count as zero |
| privacy sentinel | raw argument/result/path/session content is absent from SQLite |
| idempotent import | second import inserts zero rows |
| report contract | client/operation/month/outcome/session/latency totals are correct and helpfulness is `unmeasured` |
| CLI smoke | import/report help surfaces remain callable |

## Acceptance Criteria

- [ ] All required tests pass.
- [ ] Parser errors fail with file and line context; no string-count fallback exists.
- [ ] SQLite schema contains no raw content/path/session columns.
- [ ] A real local import returns more than zero structured codebase-memory calls.
- [ ] A second real import inserts zero duplicates.
- [ ] JSON report explicitly separates returned, transport-error,
      application-error, and missing outcomes and says helpfulness is unmeasured.
- [ ] Focused Ruff and mypy checks pass.
- [ ] Generated API reference is current.

## Notes

The ledger is separate from direct runtime `tool_calls` because transcript
evidence has a distinct provenance and can truthfully include `missing` output.
It must not be presented as semantic success. Future explicit outcome receipts
may join this reporting surface only through a separately designed contract.
