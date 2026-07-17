# Plan #106: Direct GPT-5.5 Structured Capability Truth

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful structured-output routing for DoDAF Plan 39

---

## Gap

**Current:** The curated registry marks bare direct `gpt-5.5` as supporting
native structured output, while an observed `acall_llm_structured` call through
the OpenAI Responses transport terminated with `LLMCapabilityError` for that
exact model, provider, transport, and JSON-schema combination.

**Target:** The registry reports that exact direct route as unsupported, and
the structured runtime honors the curated false value without consulting
LiteLLM's generic capability map or dispatching a provider request.

**Why:** Registry visibility must not exceed execution evidence. DoDAF can use
the separately certified direct Gemini route without preserving a false GPT-5.5
capability claim.

---

## References Reviewed

- `llm_client/data/default_model_registry.json` - curated model capability source
- `llm_client/core/models.py` - registry capability resolver
- `llm_client/execution/structured_runtime.py` - native-schema route selection
- `tests/test_structured_capability_registry.py` - registry/runtime precedence tests
- DoDAF trace `dodaf.plan39.smoke.relationship_to_jfcc.v3` - observed direct rejection
- `CLAUDE.md` - project workflow and structured-output policy

---

## Files Affected

- `llm_client/data/default_model_registry.json` (modify)
- `tests/test_structured_capability_registry.py` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/106_gpt55_structured_capability_truth.md` (create)

---

## Plan

1. Mark only bare direct `gpt-5.5` unsupported for native structured output.
2. Preserve the distinct OpenRouter GPT-5.5 capability declaration.
3. Prove registry false prevents LiteLLM fallback capability lookup.
4. Run focused registry and model-selection tests, lint, and registry JSON
   parsing. Strict MyPy is not applicable because no Python source changes.

---

## Required Tests

| Test | Evidence | Pass condition |
|------|----------|----------------|
| Direct registry regression | test, grade A | bare `gpt-5.5` is false while OpenRouter remains true |
| Runtime precedence regression | test, grade A | native-schema support is false with no LiteLLM lookup |
| Related registry suite | test, grade A | existing curated overrides and task filtering pass |

---

## Acceptance Criteria

- [x] Direct `gpt-5.5` no longer advertises native JSON-schema support.
- [x] OpenRouter GPT-5.5 remains unchanged.
- [x] Unsupported direct routing fails before generic capability fallback.
- [x] Focused tests, Ruff, and registry JSON parsing pass.
- [x] Verified commit is pushed for review (`7caf6ee`).

## Non-Goals

- Enabling GPT-5.5 structured output through another transport.
- Changing GPT-5.5 Pro without route-specific execution evidence.
- Replacing DoDAF's separately certified direct Gemini route.
