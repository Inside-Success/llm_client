# Plan #42: Codex CLI MCP Parity

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Inside Success Twitter prospecting agent

---

## Gap

**Current:** Codex SDK execution prepares an isolated home containing caller-supplied
MCP servers, while direct and automatic CLI execution ignores `mcp_servers`. The
CLI result also discards JSONL tool-call evidence, and replay snapshots retain MCP
environment values.

**Target:** Every CLI path attaches the requested MCP servers, returns bounded
tool-call evidence, cleans up its temporary home, and persists only redacted,
explicitly non-replayable MCP environment configuration.

**Why:** A caller must be able to require real tool use without transport-specific
behavior or credential disclosure.

---

## References Reviewed

- `llm_client/sdk/agents_codex.py` - Codex SDK/CLI dispatch and MCP configuration
- `llm_client/observability/replay.py` - normalized call-snapshot boundary
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` - safe replay persistence
- `docs/adr/0007-observability-contract-boundary.md` - bounded observability payloads
- `docs/adr/0003-warning-taxonomy.md` - stable warning and failure evidence
- `docs/adr/0010-cross-project-runtime-substrate.md` - shared adapter ownership
- `docs/adr/0012-shared-data-plane-boundary.md` - durable shared-data limits
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` - liveness versus
  progress evidence
- `CLAUDE.md` - project workflow and verification rules

---

## Files Affected

- `llm_client/sdk/agents_codex.py` (modify)
- `llm_client/observability/replay.py` (modify)
- `tests/test_agents.py` (modify)
- `tests/test_observability_replay.py` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/42_codex_cli_mcp_parity.md` (create)

---

## Plan

### Steps

1. Prepare and clean up the isolated Codex home inside direct CLI execution.
2. enable CLI JSONL events and normalize completed MCP calls into `LLMCallResult`.
3. Redact MCP environment values before snapshot normalization and mark replay unsupported.
4. Prove behavior with deterministic tests and a real local MCP probe.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_agents.py` | `test_call_codex_via_cli_attaches_mcp_and_returns_tool_evidence` | CLI receives an isolated MCP config and returns completed tool calls |
| `tests/test_agents.py` | `test_call_codex_via_cli_cleans_mcp_home_on_failure` | Temporary configuration is removed on subprocess failure |
| `tests/test_observability_replay.py` | `test_snapshot_redacts_mcp_environment_secrets` | Snapshot and fingerprint inputs never retain MCP environment values |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_agents.py` | Codex SDK and CLI compatibility |
| `tests/test_observability_replay.py` | Snapshot/replay contract remains coherent |

---

## Acceptance Criteria

- [x] CLI and auto-fallback paths attach caller-supplied MCP servers.
- [x] A completed CLI MCP invocation appears in `LLMCallResult.tool_calls`.
- [x] Temporary Codex homes are removed on success and failure.
- [x] Serialized call snapshots contain no MCP environment values and refuse exact replay.
- [x] Focused adapter and replay verification passes.

---

## Notes

The agent prompt owns the prospecting goal. This shared change only restores
transport parity and evidence, so it does not encode workflow-specific tool order.

The isolated configuration uses `CODEX_HOME` rather than replacing the process
`HOME`, preserving user-site dependencies for Python MCP servers. Supplied MCP
servers are required by default so failed initialization cannot silently remove
the caller's requested tools. It preserves the configured model-provider tables
from `CODEX_HOME` while stripping every ambient `mcp_servers` table before adding
the caller's explicit tools; this lets a service use a scoped provider without
silently inheriting unrelated tools.

Verified 2026-07-24:

- `tests/test_agents.py` + `tests/test_observability_replay.py`: 205 passed.
- Live `codex exec --json` + TwitterAPI.io MCP probe: `advanced_search`
  completed and returned 20 public posts.
- Full repository lint/type gates remain red from pre-existing broad baseline
  debt; full pytest collection also lacks the optional `langgraph` dependency.

Reconciled 2026-07-25:

- Renumbered from the conflicting historical Plan #119 to Plan #42.
- `tests/test_agents.py` + `tests/test_observability_replay.py`: 205 passed.
- Changed-file Ruff passed.
- The earlier live MCP probe remains the execution evidence; no new external
  call was required for reconciliation.
