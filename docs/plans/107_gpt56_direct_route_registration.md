# Plan #107: Direct GPT-5.6 Route Registration

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Truthful explicit selection of direct GPT-5.6 routes

---

## Gap

**Current:** Default OpenRouter routing rewrites bare `gpt-*` ids before the
structured runtime sees them. A strict-schema probe of bare `gpt-5.6` therefore
tested `openrouter/openai/gpt-5.6`, not OpenAI's direct Responses API. The
route was rejected even though direct `gpt-5.6` and `gpt-5.6-terra` both return
schema-valid typed output when routing is explicitly direct.

**Target:** The two observed direct GPT-5.6 routes remain direct under the
normal routing policy, appear as manual-selection registry entries, and have a
durable route-certification record. The incorrect Plan 106 GPT-5.5 disposition
is retracted rather than retained as current truth.

**Why:** A model identifier is not a route. Selection and certification must
bind the provider path, or a gateway limitation can be mislabeled as a model
limitation.

---

## References Reviewed

- `llm_client/core/provider_policy.py` - exact aliases run before the broad
  OpenRouter `gpt-*` rule.
- `llm_client/core/routing.py` - routing trace records requested and resolved
  models.
- `llm_client/execution/structured_runtime.py` - bare GPT-5 direct routes use
  Responses API native JSON Schema.
- `docs/guides/model-selection.md` - declared versus certified route policy.
- `docs/plans/106_gpt55_structured_capability_truth.md` - superseded direct
  GPT-5.5 claim.
- `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md` -
  retained direct-route probes for this plan.

## Files Affected

- `llm_client/core/provider_policy.py` (modify)
- `llm_client/data/default_model_registry.json` (modify)
- `tests/test_provider_policy.py` (modify)
- `tests/test_routing.py` (modify)
- `tests/test_structured_capability_registry.py` (modify)
- `docs/guides/model-selection.md` (modify)
- `docs/plans/106_gpt55_structured_capability_truth.md` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md` (create)

## Plan

1. Preserve direct `gpt-5.6` and `gpt-5.6-terra` through exact provider-policy
   aliases before default OpenRouter normalization.
2. Register only those observed routes as manual-selection structured-output
   candidates; do not change a tier default from this capability probe.
3. Replace Plan 106's incorrect direct-GPT-5.5 assertion with its actual
   OpenRouter-scoped evidence and record the correction.
4. Add routing and capability tests that discriminate direct and OpenRouter
   paths, then retain the live probe evidence in the route guide.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_provider_policy.py` | `test_canonicalizes_exact_aliases_before_route_selection` | GPT-5.6 direct aliases bypass the broad OpenRouter rule. |
| `tests/test_routing.py` | `test_resolve_call_gpt56_preserves_certified_direct_route_under_openrouter_policy` | Normal routing keeps certified GPT-5.6 direct. |
| `tests/test_routing.py` | `test_resolve_call_gpt56_terra_preserves_certified_direct_route_under_openrouter_policy` | Terra has the same direct-route guarantee. |
| `tests/test_structured_capability_registry.py` | `test_observed_direct_gpt_routes_advertise_native_schema_support` | Registry declares the observed direct routes and preserves the separate proxy record. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_provider_policy.py` | Provider aliases remain explicit and typed. |
| `tests/test_routing.py` | Route normalization and direct/proxy separation remain coherent. |
| `tests/test_structured_capability_registry.py` | Registry capability declarations remain authoritative. |
| `tests/test_models.py` | Static model selection remains coherent after registry additions. |

### Observed Evidence

The retained live probe proves that direct Responses API accepted strict JSON
Schema and returned typed content; it is evidence in addition to, not a
replacement for, the deterministic route tests above.

## Acceptance Criteria

| Criterion | Grade target | Verification |
|---|---|---|
| Direct and OpenRouter GPT routes cannot be confused | A | routing tests plus retained requested/resolved-model evidence |
| `gpt-5.6` and `gpt-5.6-terra` are explicitly selectable | A | registry test plus exact alias tests |
| No model tier default is silently changed | A | model-selection guide and selector tests |
| Plan 106 no longer states a false direct-route result | A | correction note cites the retained recheck |

## Non-Goals

- Comparing semantic quality among GPT-5.6, MiniMax, Grok, or DeepSeek.
- Promoting either GPT-5.6 route to an automatic tier default.
- Certifying GPT-5.6 Luna or any OpenRouter GPT-5.6 route.

## Completion Evidence

- `python scripts/meta/check_plan_tests.py --plan 107` - all named tests pass.
- `pytest tests/test_provider_policy.py tests/test_routing.py
  tests/test_structured_capability_registry.py tests/test_models.py -q` - 77 passed.
- Live strict-schema call under normal routing: requested/resolved
  `gpt-5.6`/`gpt-5.6`, `routing_policy=openrouter_on`, one typed response;
  trace `llm_client/gpt56-direct-native-schema-certification/v4-plan107`.
- `make check` remains blocked before this plan's tests by the existing `main`
  Ruff baseline: 307 findings at source revision `68426c2`; this increment adds
  none and does not suppress the gate.

## Process Limitation

Rebasing this PR after `main` advanced changes the published commit ids. The
environment blocks `git push --force-with-lease`, even for this agent's own
unshared PR branch, so the rebased increment must be published through a new
branch and PR rather than rewriting the existing PR head. This is recorded as
pending policy friction under `force-push-publication-recovery`.
