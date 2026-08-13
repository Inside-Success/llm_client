# Plan #357: Nested Tool-Loop Model Justification

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Open Web Retrieval agent-driven MVP M1 canary

---

## Gap

**Current:** `acall_llm(..., python_tools=..., model_justification=...)`
authorizes the outer route, but `text_runtime` removes the justification before
the direct tool loop makes its nested model turn. The nested call then fails
the exact-model execution policy before provider or tool dispatch.

**Target:** Preserve the already-authorized justification across nested MCP and
direct Python-tool model turns while continuing to strip it before provider
transport.

**Why:** Tool loops cannot use any allowed non-default model even when the
caller supplies the required policy evidence. The defect directly blocks an
authentic Open Web Retrieval agent from constructing an OpenAlex call.

---

## References Reviewed

- `llm_client/execution/text_runtime.py` — outer policy resolution and nested
  MCP/Python-tool routing.
- `llm_client/agent/mcp_agent.py` — nested direct-tool runtime.
- `llm_client/core/model_execution_policy.py` — exact-model justification rule.
- `docs/adr/0002-routing-config-precedence.md` — explicit call policy wins.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — policy
  inputs remain replayable without becoming provider payload.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` — allowed
  non-default models require retained justification.
- `docs/plans/117_explicit_reasoning_policy.md` — nested calls preserve explicit
  execution policy.

---

## Files Affected

- `llm_client/execution/text_runtime.py`
- `tests/test_tool_utils.py`
- `tests/test_mcp_agent.py`
- `docs/plans/357_nested_tool_model_justification.md`
- `docs/plans/CLAUDE.md`

---

## Plan

1. Re-inject the validated outer `model_justification` into nested tool-loop
   runtime kwargs only.
2. Add a direct Python-tool routing regression test.
3. Verify provider-kwarg isolation with existing model-policy tests.
4. Rerun the exact Open Web Retrieval M1 canary against the feature revision.

---

## Required Tests

| Test | What It Verifies |
|---|---|
| `test_routes_model_justification_to_nested_tool_loop` | Nested direct-tool turns receive the caller's justification |
| `test_non_agent_with_mcp_routes_model_justification` | Nested MCP turns receive the same justification |
| `tests/test_model_execution_policy.py` | Justification remains local policy and never provider payload |
| OWR M1 live canary | A real model constructs and executes the OpenAlex tool call |

---

## Acceptance Criteria

- [x] Nested direct Python-tool and MCP turns retain the validated justification.
- [x] Provider kwargs do not receive `model_justification`.
- [x] Focused tests pass.
- [x] The authentic OWR M1 canary passes the repaired boundary and exposes a
  distinct OpenAlex semantic-mode 504.

## Rollback

Revert the single propagation change. The prior behavior fails closed before a
non-default nested model turn and performs no provider or tool I/O.

## Runtime Evidence

- M1 canaries 1 and 2 reproduced the missing nested justification before any
  provider or tool I/O.
- Canary 3 with this repair passed local policy and reached OpenRouter. The
  selected Minimax route then returned a distinct no-compatible-endpoint 404;
  no tool call executed and recorded cost was `$0.00`.
- Canary 6 used the executable-policy default GPT-5.6 Luna route. The model
  selected `semantic`, constructed a contextual multi-explanation query and
  rationale, and invoked `openalex_search`. OpenAlex returned HTTP 504; an
  exact tool-only replay returned the same 504. The model/tool run cost was
  `$0.0004814`, proving the repaired nested policy boundary while isolating the
  remaining failure to OpenAlex semantic execution.
- Verification: `77 passed` across direct-tool routing, MCP routing, and exact
  model-policy tests; critical Ruff selectors and `git diff --check` passed.
