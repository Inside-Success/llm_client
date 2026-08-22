# Plan #363: Codex CLI Session Continuation

**Status:** Implemented (provider-free)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** AC16 Plan #02 exact-session healing harness
**Landscape disposition:** linked
**Critical-path classification:** direct blocker for AC16; shared-runtime enabler

---

## User Outcome

AC16 can ask the public shared client to resume the exact builder or healer
Codex session, retain its native capabilities, and receive evidence that the
requested session store and identity were actually used.

## Gap

**Current:** `llm_client` starts a fresh Codex thread on every call. The CLI
result records its session ID, but callers cannot pass that identity back
through the shared execution boundary. A downstream recovery controller must
either bypass `llm_client` or incorrectly substitute a fresh agent for
same-session healing.

**Target:** Add explicit `fresh`, `resume`, and `fork` session controls to the
Codex CLI adapter. Validate their identity contract before dispatch, reject
continuation on SDK/auto transports, and retain the existing returned session
receipt.

**Why:** Session routing is shared transport behavior. Recovery policy and role
ownership remain downstream, but callers must not recreate Codex subprocess,
timeout, event, billing, or observability ownership to continue one session.

## Landscape And Prior Art

**Disposition:** linked. This extends the existing CLI transport and event
custody boundary rather than adding a second subprocess or telemetry owner.
Codex's native resume/fork subcommands remain the execution mechanism; the
[Codex integration guide](../guides/codex-integration.md) is the public
contract extended here.

## Critical Path Classification

**Direct blocker:** AC16 cannot truthfully demonstrate same-session healing
through the required shared-client seam without this capability. The change is
also an **enabler** for other recovery controllers; it is not itself a product
vertical or evidence that AC16 succeeds.

---

## References Reviewed

- `CLAUDE.md` and `llm_client/sdk/CLAUDE.md` - repository and adapter rules.
- `docs/adr/0010-cross-project-runtime-substrate.md` - shared execution and
  observability ownership.
- `docs/adr/0005-reason-code-registry-governance.md` - stable fail-loud reason
  semantics at shared runtime boundaries.
- `docs/adr/0006-actor-id-issuance-policy.md` - explicit actor/session identity
  custody rather than inferred identity.
- `docs/guides/codex-integration.md` - existing public Codex transport contract.
- `docs/plans/355_codex_intrinsic_event_custody.md` - existing Codex result and
  event-custody boundary.
- `llm_client/sdk/agents.py` - agent-specific public kwarg extraction.
- `llm_client/sdk/agents_codex.py` - CLI command, transport, timeout, result, and
  session receipt implementation.
- Installed Codex CLI `exec resume --help` and `exec fork --help` - exact
  subcommand grammar and option placement.
- AC16 Plan #02 provider-free harness - named consumer and reproduced gap.

---

## Files Affected

- `llm_client/sdk/agents.py` (modify)
- `llm_client/sdk/agents_codex.py` (modify)
- `tests/test_agents.py` (modify)
- `docs/guides/codex-integration.md` (modify)
- `docs/plans/363_codex_session_continuation.md` (create)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. **direct_blocker:** Add failing provider-free tests for fresh/resume/fork command construction,
   persistent-home custody, malformed identity receipts, non-CLI refusal, and
   public kwarg propagation.
2. Add the two agent kwargs and one fail-loud session validator.
3. Render continuation with global filesystem controls before the nested Codex
   exec subcommand, name the exact session explicitly, and require a stable
   caller-owned Codex home for every explicit session lineage.
4. Document the public contract and run adapter regression checks.
5. Pin AC16 to the merged revision and prove downstream resume routing without
   launching a model.

---

## Required Tests

| Test | What It Verifies |
|---|---|
| `test_build_codex_cli_command_targets_exact_session` | resume/fork render the exact identity with valid global isolation options |
| `test_build_codex_cli_command_rejects_invalid_session_contract` | fresh/continuation identity invariants fail before dispatch |
| `test_codex_session_continuation_rejects_non_cli_transport` | SDK/auto cannot impersonate exact continuation |
| `test_public_codex_cli_call_resumes_exact_session` | public kwargs reach the owned CLI seam and retain the returned identity |
| `test_codex_cli_fresh_resume_fork_share_persistent_home_and_prove_identity` | a three-call adapter lifecycle reuses storage and proves fresh/resume/fork identities |
| `test_codex_cli_rejects_unproven_or_wrong_session_receipt` | missing, mismatched, and non-forked identities fail closed |
| `test_codex_session_continuation_rejects_streaming_routes` | sync/async streaming cannot silently replace an explicit session with a fresh SDK thread |
| existing `TestCodexFallback` tests | fresh CLI, timeout, capability, event, and result behavior remains stable |

---

## Acceptance Criteria

- [x] Fresh calls remain the default and reject an accidental parent identity.
- [x] Resume/fork require one explicit, validated session identity.
- [x] Explicit session lineages require a persistent caller-owned Codex home;
      ordinary one-shot calls retain temporary-home isolation.
- [x] Continuation renders only on the CLI transport and never uses `--last`.
- [x] Successful calls require a JSONL session receipt; resume equality and
      fork inequality are enforced before a result is accepted.
- [x] Sync and async streaming reject explicit session modes until exact CLI
      continuation streaming exists.
- [x] Existing working-directory, sandbox, model, effort, network, search, MCP,
      timeout, and returned-session behavior remains owned by `llm_client`.
- [x] Focused provider-free tests pass without launching Codex.
- [ ] AC16 pins the merged revision and proves exact-role resume routing through
      this shared seam; that downstream adoption is a separate unit.

## Canonical Behavioral Example

Given a dedicated Codex home and the session ID returned by a successful fresh
builder call, a resume call names that ID, runs against the same home, and is
accepted only when `thread.started.thread_id` equals the requested ID. A fork
against that parent is accepted only when the returned ID differs.

---

## Reset Boundary

This does not add workflow checkpoints, choose a recovery target, or claim that
a fresh/forked session is equivalent to a resumed session. If a future Codex
SDK exposes stable continuation, add it through a separate transport-parity
change rather than silently relaxing the current CLI-only check.

## Notes

Implementation used the sanctioned light-work fallback because this repository
still has no configured plan-readiness query command. The code and plan remain
isolated in a claimed worktree. No provider or model call is part of this unit.
