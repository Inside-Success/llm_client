# Plan #337: Current Model Selection Evidence and GPT-5.5 Retirement

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Truthful shared model guidance

---

## Gap

**Current:** Model guidance uses a broad informal scorecard, still advertises
GPT-5.5 as the `max_intelligence` tier, and marks Luna structured output false
despite current provider support and one retained local contract pass.

**Target:** Use one current six-field decision card; hard-block and remove all
GPT-5.5 routes; select GPT-5.6 Sol for `max_intelligence`; correct Luna's
declared structured-output capability without overstating contract coverage.

**Why:** A fail-closed allowlist and selection guide must agree with adopted
policy. Current model data must separate public benchmarks, provider-declared
capability, and retained local route evidence.

---

## References Reviewed

- `CLAUDE.md` - repository governance and test requirements.
- `docs/guides/model-selection.md` - current selectors and route evidence.
- `llm_client/core/model_execution_policy.py` - exact execution allowlist.
- `llm_client/data/default_model_registry.json` - selector inputs.
- `llm_client/execution/call_contracts.py` - family-level hard blocks.
- Artificial Analysis Intelligence Index v4.1 and current model pages,
  observed 2026-07-28.
- OpenRouter `GET /api/v1/models`, observed 2026-07-28.
- OpenAI and DeepSeek official model documentation, observed 2026-07-28.

---

## Files Affected

- `docs/guides/model-selection.md`
- `docs/API_REFERENCE.html`
- `docs/API_REFERENCE.md`
- `docs/plans/337_current-model-selection-evidence-and-gpt-5-5-retirement.md`
- `docs/plans/CLAUDE.md`
- `llm_client/core/model_execution_policy.py`
- `llm_client/data/default_model_registry.json`
- `llm_client/execution/call_contracts.py`
- `llm_client/model_policy_audit.py`
- `tests/test_client.py`
- `tests/test_model_execution_policy.py`
- `tests/test_model_policy_audit.py`
- `tests/test_models.py`
- `tests/test_structured_capability_registry.py`

---

## Plan

1. Add the six-field decision card and dated evidence table.
2. Remove GPT-5.5 exact routes and reasoning capabilities; hard-block the
   family before dispatch and flag literals in repository audits.
3. Remove GPT-5.5 registry entries, assign GPT-5.6 Sol to
   `tier-max-intelligence`, and correct Luna's declared structured capability.
4. Add focused policy, registry, selector, and audit regressions.
5. Run focused tests and repository validators; reconcile documentation with
   observed behavior.

---

## Required Tests

| Test surface | What it verifies |
|---|---|
| `tests/test_model_execution_policy.py` | No GPT-5.5 route remains allowlisted or reasoning-configurable. |
| `tests/test_client.py` | `TestModelDeprecation` proves direct and OpenRouter GPT-5.5 aliases fail before dispatch. |
| `tests/test_models.py` | Registry omits GPT-5.5, Luna declaration is true, and max tier selects Sol. |
| `tests/test_structured_capability_registry.py` | Current declarations omit GPT-5.5 and retain Luna/Sol/Terra capability truth. |
| `tests/test_model_policy_audit.py` | GPT-5.5 literals are denied even with override metadata. |

---

## Acceptance Criteria

- [x] Exact execution policy and registry contain no GPT-5.5 route.
- [x] Every GPT-5.5 alias fails before provider dispatch.
- [x] `max_intelligence` deterministically selects OpenRouter GPT-5.6 Sol.
- [x] Luna is declared structured-capable but certified only for named retained
      contracts.
- [x] Focused tests and deterministic slice validators pass.
- [x] Guide records sources, effort, and observation date for mutable metrics.

---

## Verification

- Focused policy, registry, selector, audit, and deprecation suite:
  `123 passed`.
- Plan test harness found every declared test file and completed with
  `365 passed`.
- Broad regression suite excluding three known baseline/environment modules:
  `1896 passed, 47 skipped, 11 deselected`.
- Ruff passed for every changed Python file. `tests/test_client.py` required
  ignoring its pre-existing `F401`, `F811`, and `F841` debt.
- Relationship validation, registry JSON parsing, and `git diff --check`
  passed.
- Full `make check` remains blocked by 299 pre-existing lint findings outside
  this slice. The unmodified LangGraph test requires the optional `langgraph`
  dependency; provider-limit subprocess tests invoke a Python without
  Pydantic; and the public-surface baseline expects 138 exports while the
  current package exposes 140.

---

## Notes

This is not a task-specific model bake-off. It resolves choices that follow
from current policy and first principles. A Process Tracing comparison is only
warranted later if two polished, route-certified candidates remain
decision-equivalent.
