# Plan #94: Model Tier Taxonomy and Fable Ban

**Status:** In Progress (tier selectors implemented; route certification follow-up open)
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
- OpenRouter API reference — the completion response supplies a generation ID;
  the authenticated generation metadata endpoint returns the actual
  `provider_name` and `upstream_id` for that generation.
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
- [x] The public selection guide defines task-shape defaults for bulk structured
      work, ordinary structured reasoning, difficult semantic authoring, and
      explicit escalation.
- [x] The guide distinguishes registry-declared structured capability from a
      runtime-certified `model + route + execution mode + schema class`.
- [x] The guide carries a route-by-route observed-status inventory, with scoped
      evidence for DeepSeek V4 Flash, MiniMax M3, Grok 4.5, Gemini Flash, and
      direct GPT-5.5 rather than a generic supported/unsupported claim.
- [x] An immutable exact-key route observation registry separates durable
      transport proof from latest route health.
- [x] An authenticated OpenRouter generation-evidence reader and trusted
      post-call compiler bind the public result, selected-attempt receipt,
      provider-facing schema digest, OpenRouter-reported `provider_name`, and
      exact successful `endpoint_id` when available. The compiler records
      OpenRouter's actual returned model permaslug rather than assuming the
      requested alias was the executed model.
- [x] An agent-drivable CLI queries one exact model + provider + execution mode
      + schema class + schema digest without inferring support from the static
      registry.
- [x] Generation-metadata enrichment handles OpenRouter's observed eventual
      consistency with bounded, logged 404-only retries. These retries do not
      repeat the model call or select another provider, and the evidence records
      the retrieval attempt count.
- [ ] The active provider-compatible native-schema repair must land before the
      compiler is invoked automatically from the structured runtime. Until then,
      callers explicitly run the post-call compiler; unknown provider identity
      never certifies a named route.
- [ ] A task-configured technical output ceiling is implemented.

### Runtime route-certification follow-up (2026-07-16)

The first disjoint implementation slice adds immutable typed observations and
an exact-key query store. Certification is bound to resolved model, actual
upstream endpoint, execution mode, schema class, and schema digest. A parseable
response with an unknown endpoint remains observational rather than certifying
a named route. Prior transport proof and latest route health are separate, so a
later timeout remains visible without erasing evidence that the exact route once
accepted and returned the schema.

Automatic emission remains blocked on the active provider-compatible schema
repair because the runtime must first preserve the actual OpenRouter endpoint.
The registry module does not modify routing or infer endpoint identity from the
requested model. Task-configured output ceilings remain a separate follow-up.

---

## Verification Evidence

- `pytest -q tests/test_models.py tests/test_model_policy_audit.py tests/test_client.py::TestModelDeprecation` — passed, 68 tests.
- `.venv/bin/python -m pytest -q tests/test_models.py::TestGetModel::test_tier_selectors_resolve_expected_models tests/test_models.py::TestGetModel::test_legacy_task_selectors_remain_compatible tests/test_models.py::TestConfigLoading::test_packaged_registry_has_no_fable_models tests/test_model_policy_audit.py::test_scan_paths_flags_banned_fable_even_with_override_acceptance tests/test_client.py::TestModelDeprecation::test_fable_raises` — passed, 5 tests.
- `.venv/bin/python scripts/meta/complete_plan.py --plan 94 --skip-e2e` — failed because the full unit-test subprocess timed out at 300 seconds after collection; doc-code coupling passed. Policy friction logged in `project-meta/policy_friction.md`.
- `pytest -q tests/test_route_certification.py tests/test_openrouter_generation.py tests/test_route_certification_runtime.py tests/test_cli_route_certification.py` — exact observation, authenticated provider evidence, three-source join, corruption, substitution, cache, and CLI query coverage.

---

## Notes

Forcing every project through `llm_client` should be a staged policy: first
visibility and audit, then enforcement for production/shared code, with explicit
exceptions for benchmark baselines, external SDK demos, and workspace-agent SDK
lanes. Agentic Codex/Claude Code usage is an execution-mode decision
(`execution_mode="workspace_agent"`), not a raw model tier.
