# Plan #94: Model Tier Taxonomy and Fable Ban

**Status:** In Progress (implemented; focused verified; full helper timeout)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cross-project model-selection cleanup

---

## Gap

**Current:** The model registry exposes task-shaped selectors such as
`extraction`, `judging`, and `bulk_cheap`. Those names mix application intent
with model-selection policy, making it hard to express speed/cost/intelligence
tradeoffs or to distinguish raw chat-model routing from workspace-agent SDK
routing.

**Target:** Add first-class tier selectors (`ultra_fast_low_intel`,
`ultra_cheap_low_intel`, `fast_cheap_mid`, `fast_mid`,
`default_intelligent`, `fast_intelligent`, `very_intelligent`,
`max_intelligence`) while keeping existing task selectors as compatibility
aliases. Ban Fable-family models at runtime and in policy audit.

**Why:** Project code should ask for a model capability tier, not encode a
provider/model string or overload a task name. Banned models must fail loudly
even when a project carries generic human override metadata.

---

## References Reviewed

- `CLAUDE.md` — repo workflow and shared-infrastructure rules.
- `llm_client/llm_client/CLAUDE.md` — package surface rules.
- `llm_client/tests/CLAUDE.md` — deterministic test expectations.
- `llm_client/data/default_model_registry.json` — packaged model/task registry.
- `llm_client/core/models.py` — registry loading and task selection.
- `llm_client/model_policy_audit.py` — cross-project raw model literal scanner.
- `llm_client/execution/call_contracts.py` — hard-blocked/deprecated model gate.
- `docs/guides/codex-integration.md` — workspace-agent execution-mode guidance.
- Artificial Analysis leaderboard snapshot reviewed in the user session for
  speed/cost/intelligence tier candidates.

---

## Files Affected

- `llm_client/data/default_model_registry.json` (modify)
- `llm_client/core/models.py` (modify docs/validation only if needed)
- `llm_client/model_policy_audit.py` (modify)
- `llm_client/execution/call_contracts.py` (modify)
- `docs/guides/model-selection.md` (create)
- `tests/test_models.py` (modify)
- `tests/test_model_policy_audit.py` (modify)
- `tests/test_client.py` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

### Steps

1. Add tier selectors to the packaged registry and map existing task selectors
   to compatibility policy.
2. Add a runtime hard block for Fable-family models.
3. Extend the policy audit so Fable literals are violations even when generic
   `model_override_acceptance` metadata exists.
4. Add focused tests for tier resolution, compatibility selectors, and the
   Fable ban.
5. Document the distinction between raw model tiers and workspace-agent SDK
   execution lanes.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_models.py` | `test_tier_selectors_resolve_expected_models` | New tier selectors resolve to intended registry candidates. |
| `tests/test_models.py` | `test_legacy_task_selectors_remain_compatible` | Existing task selectors still work. |
| `tests/test_model_policy_audit.py` | `test_scan_paths_flags_banned_fable_even_with_override_acceptance` | Audit denylist beats generic override acceptance. |
| `tests/test_client.py` | `test_fable_raises` | Runtime calls hard-block Fable-family models. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest -q tests/test_models.py tests/test_model_policy_audit.py tests/test_client.py::TestModelDeprecation` | Registry, audit, and runtime model policy contracts. |

---

## Acceptance Criteria

- [x] Tier selectors exist and are documented.
- [x] MiniMax-M3 remains the `default_intelligent` selector.
- [x] Existing task selectors remain backward compatible.
- [x] Fable-family models are hard-blocked at runtime.
- [x] Fable-family literals are audit violations even with generic override
      acceptance.
- [x] Focused tests pass.

---

## Verification Evidence

- `pytest -q tests/test_models.py tests/test_model_policy_audit.py tests/test_client.py::TestModelDeprecation` — passed, 68 tests.
- `.venv/bin/python -m pytest -q tests/test_models.py::TestGetModel::test_tier_selectors_resolve_expected_models tests/test_models.py::TestGetModel::test_legacy_task_selectors_remain_compatible tests/test_models.py::TestConfigLoading::test_packaged_registry_has_no_fable_models tests/test_model_policy_audit.py::test_scan_paths_flags_banned_fable_even_with_override_acceptance tests/test_client.py::TestModelDeprecation::test_fable_raises` — passed, 5 tests.
- `.venv/bin/python scripts/meta/complete_plan.py --plan 94 --skip-e2e` — failed because the full unit-test subprocess timed out at 300 seconds after collection; doc-code coupling passed. Policy friction logged in `project-meta/policy_friction.md`.

---

## Notes

Forcing every project through `llm_client` should be a staged policy: first
visibility and audit, then enforcement for production/shared code, with explicit
exceptions for benchmark baselines, external SDK demos, and workspace-agent SDK
lanes. Agentic Codex/Claude Code usage is an execution-mode decision
(`execution_mode="workspace_agent"`), not a raw model tier.
