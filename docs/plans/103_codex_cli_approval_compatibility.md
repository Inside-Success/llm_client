# Plan #103: Codex CLI Approval Compatibility

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** ecosystem-ops direct Codex dispatch certification

---

## Gap

**Current:** The Codex CLI command builder maps `approval_policy="never"` to
`--dangerously-bypass-approvals-and-sandbox` and maps every other policy to the
removed `-a` option. Codex CLI 0.144.1 therefore either discards the requested
sandbox or rejects the command before execution.

**Target:** Ordinary approval policies are passed through the supported config
override while preserving the requested sandbox. Only explicit
`yolo_mode=True` licenses the bypass flag.

**Why:** A headless caller must be able to run a bounded Codex agent without
silently widening its filesystem authority.

---

## References Reviewed

- `llm_client/sdk/agents_codex.py:_build_codex_cli_command` — current CLI command mapping.
- `llm_client/sdk/agents.py:_apply_agent_yolo_defaults` — explicit autonomous convenience contract.
- `tests/test_agents.py:TestCodexFallback` — existing command and subprocess coverage.
- `codex exec --help` from Codex CLI 0.144.1 — current supported command surface.

---

## Files Affected

- `llm_client/sdk/agents_codex.py` (modify)
- `tests/test_agents.py` (modify)
- `docs/plans/103_codex_cli_approval_compatibility.md` (create)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Add negative-first command tests for safe `never`, another approval policy,
   and explicit yolo behavior.
2. Replace the removed CLI flag with a typed config override; reserve the
   bypass switch for explicit yolo mode.
3. Run focused tests and real read-only positive/invalid-dependency probes.

---

## Required Tests

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_agents.py` | `test_build_codex_cli_command_preserves_sandbox_for_never_approval` | `never` uses supported config and does not bypass the sandbox. |
| `tests/test_agents.py` | `test_build_codex_cli_command_forwards_non_never_approval` | Other policies do not emit removed `-a`. |
| `tests/test_agents.py` | existing yolo command test | Explicit yolo still emits the bypass switch. |

---

## Acceptance Criteria

- [x] **AC1 (test, grade A):** focused command tests distinguish safe policy
  forwarding from explicit yolo bypass.
- [x] **AC2 (observed, grade B):** the real `llm_client` CLI transport returns
  the expected response under `sandbox_mode="read-only"` and leaves its
  temporary workspace unchanged.
- [x] **AC3 (test + observed, grade A):** an invalid CLI dependency fails loudly before a
  capability can be advertised.

---

## Notes

This is a narrow compatibility repair, not a new provider route. The dashboard
remains unavailable until its own deployed UI-action composition is verified.

Observed 2026-07-15 against Codex CLI 0.144.1: the positive trace
`ecosystem_ops.command_room.codex_direct.valid.20260715.v2` returned
`CODEX_DIRECT_OK` through `codex_cli`, reported subscription-included billing,
and left the temporary read-only workspace empty. The missing-CLI trace
`ecosystem_ops.command_room.codex_direct.missing_cli.20260715` produced one
failed `llm_calls` row with `FileNotFoundError`; the positive trace produced one
successful terminal row. `tests/test_agents.py` passes 138/138. Repository-wide
Ruff and strict mypy remain red on pre-existing unrelated findings; neither
reported a finding introduced on the changed command-builder lines.
