# Plan #360: Codex Subscription Default

**Status:** Implemented (focused verification)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** visible, justification-backed OpenRouter exceptions

---

## Gap

**Current:** The shared execution default is the metered
`openrouter/openai/gpt-5.6-luna` route, even though the reviewed Codex Luna
subscription route is already certified for compatible agentic workloads.

**Target:** `codex/gpt-5.6-luna` is the shared default. Any non-default
allowlisted route, including OpenRouter, requires `model_justification`, which
is retained in routing and replay evidence.

**Why:** Sustained compatible work should consume the approved subscription
lane first, while preserving a visible exception path for model breadth,
intermittent use, access constraints, unavailable capabilities, and genuine
subscription-route failures.

---

## References Reviewed

- `llm_client/core/model_execution_policy.py` — exact route allowlist and
  default/exception enforcement seam.
- `tests/test_model_execution_policy.py` — existing default and
  justification-contract coverage.
- `docs/plans/340_codex_luna_subscription_route.md` — authenticated Codex Luna
  subscription-route evidence.
- `docs/plans/348_gpt54_ban_luna_default.md` — shared default policy history.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` —
  provider-selection and trace/replay authority.

## Files Affected

- `llm_client/core/model_execution_policy.py` (modify)
- `tests/test_model_execution_policy.py` (modify)
- `README.md` (modify)
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

## Plan

1. Set the shared execution default to the certified Codex Luna subscription
   identity without changing the allowlist.
2. Prove the default does not require an exception reason and that OpenRouter
   Luna does.
3. Keep the public quick-start compatible with Codex's required explicit
   reasoning effort and record the decision boundary.

## Required Tests

| Test | What it proves |
|---|---|
| `tests/test_model_execution_policy.py` | The Codex subscription route is default; OpenRouter selection is explicit and traceable. |

## Acceptance Criteria

- [x] `DEFAULT_EXECUTION_MODEL` is `codex/gpt-5.6-luna`.
- [x] A default route needs no `model_justification` and uses supported explicit reasoning.
- [x] An OpenRouter Luna route without a justification fails before dispatch.
- [x] Focused policy tests and generated API reference are current.

## Verification Evidence

- `pytest tests/test_model_execution_policy.py -q -rA`: 29 passed.
- `ruff check llm_client/core/model_execution_policy.py
  tests/test_model_execution_policy.py`: passed.
- `scripts/meta/generate_api_reference.py --write`: regenerated Markdown and
  HTML API references with `DEFAULT_EXECUTION_MODEL='codex/gpt-5.6-luna'`.

The full suite was not run; this is a focused routing-policy increment.

## Non-Claims

- This does not automatically reroute explicit caller selections.
- This does not remove OpenRouter fallbacks or guarantee Codex availability.
- This does not certify every workload for Codex subscription execution.
