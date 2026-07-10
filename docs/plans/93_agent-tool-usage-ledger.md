# Plan #93: Agent tool-usage ledger

**Status:** Complete — scoped verification; repository-wide dependency and Ruff baselines remain open
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
| outcome maturation | a later result replaces provisional `missing` evidence exactly once |
| report contract | client/operation/month/outcome/session/latency totals are correct and helpfulness is `unmeasured` |
| CLI smoke | import/report help surfaces remain callable |

## Acceptance Criteria

- [x] All required tests pass.
- [x] Parser errors fail with file and line context; no string-count fallback exists.
- [x] SQLite schema contains no raw content/path/session columns.
- [x] A real local import returns more than zero structured codebase-memory calls.
- [x] A second real import inserts zero duplicates.
- [x] JSON report explicitly separates returned, transport-error,
      application-error, and missing outcomes and says helpfulness is unmeasured.
- [x] Focused Ruff and mypy checks pass.
- [x] Generated API reference is current.

## Verification Evidence

- 81 focused observability, CLI, defaults, I/O-log, and API-generation tests
  pass.
- Focused Ruff and mypy checks pass for every changed Python surface.
- API reference regeneration followed by `--check` passes in the declared
  repository command environment.
- A privacy-preserving import scanned 3,005 transcript files, explicitly
  skipped 32 malformed files, found 1,366 structured events, and retained
  1,336 unique calls after collapsing duplicate transcript representations.
- Repeating the identical import inserted zero new rows and classified all
  1,366 observations as duplicates.
- The report contains 1,209 returned, 118 application-error, 6
  transport-error, and 3 missing outcomes; helpfulness remains `unmeasured`.
- Repository-wide `make check` stops on 317 pre-existing Ruff findings tracked
  by LLM-001. Full `pytest -q` stops during collection because the current
  environment lacks the optional `langgraph` dependency. Neither failure is
  in a changed or directly dependent surface, so they are recorded rather than
  silently waived.
- Independent pre-landing review found that `INSERT OR IGNORE` froze a call as
  `missing` when a later transcript import contained its result. The persistence
  contract now permits only `missing` to mature to a terminal outcome, reports
  updates separately from duplicates, and has a three-import negative control.
- The reproducible focused type command is `mypy --strict
  --follow-imports=silent llm_client/observability/agent_tool_usage.py
  llm_client/cli/tool_usage.py`; plain strict mypy traverses the known
  repository-wide baseline and is not evidence for this slice.

## Notes

The ledger is separate from direct runtime `tool_calls` because transcript
evidence has a distinct provenance and can truthfully include `missing` output.
It must not be presented as semantic success. Future explicit outcome receipts
may join this reporting surface only through a separately designed contract.
