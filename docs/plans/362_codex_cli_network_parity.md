# Plan #362: Codex CLI Network Parity

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** research_v3 Plan #38

---

## Gap

**Current:** The Codex SDK adapter accepts `network_access_enabled` and
`web_search_enabled`, but the installed CLI fallback drops both controls. A
workspace-agent can discover a networked OSINT CLI and then fails every
government API request inside a network-restricted sandbox.

**Target:** The CLI command maps network access to Codex's
`sandbox_workspace_write.network_access` setting and maps web search to the
native `--search` flag, while retaining workspace-write filesystem isolation.

**Why:** Subscription-agent consumers need the same declared capabilities on
SDK and CLI transports; silently dropping them creates misleading successful
agent runs.

---

## References Reviewed

- `CLAUDE.md` - repository governance and required call contract.
- `docs/guides/codex-integration.md` - documented SDK/CLI transport behavior.
- `llm_client/sdk/agents_codex.py:630-690` - exact CLI command builder.
- `tests/test_agents.py:2241-2325` - focused CLI command tests.
- Installed Codex 0.149 help and binary config schema - workspace-write network
  setting and native search flag.
- `research_v3` Plan #38 run `run_20260822_3` - authentic DNS failure receipts.

---

## Files Affected

- `llm_client/sdk/agents_codex.py` (modify)
- `tests/test_agents.py` (modify)
- `docs/guides/codex-integration.md` (modify)
- `docs/plans/351_codex_cli_network_parity.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Add failing command-rendering coverage for network and search controls.
2. Forward the two existing public controls through the CLI command builder.
3. Run focused adapter tests and an authentic research_v3 OSINT canary.
4. Document the parity behavior and close the plan.

---

## Required Tests

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_agents.py` | `test_build_codex_cli_command_forwards_network_and_search` | CLI retains workspace isolation while enabling requested network/search |
| `tests/test_agents.py` | existing Codex CLI command tests | Existing sandbox, approval, model, and effort rendering stays stable |

---

## Acceptance Criteria

- [ ] `network_access_enabled=True` renders the workspace-write network setting.
- [ ] `web_search_enabled=True` renders the native search flag.
- [ ] Existing focused Codex adapter tests pass.
- [ ] A CLI-fallback agent can obtain a successful retained USAspending receipt.
- [ ] No danger-full-access mode or metered fallback is introduced.

---

## Notes

This is transport propagation only. It does not alter capability defaults:
callers must still explicitly request network access or web search.
