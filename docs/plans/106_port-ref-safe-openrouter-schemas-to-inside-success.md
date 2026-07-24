# Plan #106: Port ref-safe OpenRouter schemas to Inside Success

**Status:** In Progress
**Type:** implementation  <!-- implementation | design -->
**Priority:** High
**Blocked By:** None
**Blocks:** DIGIMON Plan 179 dependency pin and Plan 36 trace regeneration

---

## Gap

**Current:** The Inside Success release branch descends from DIGIMON's pinned
`d74b8eac` revision but does not contain the personal-upstream OpenRouter
provider projections merged in PR #81 (disjoint `oneOf` to `anyOf`) and PR #89
(`$ref` sibling normalization). A workspace editable checkout masked that
release gap: Luna accepted a multi-action planner schema from the newer local
source, while the exact pinned package cannot represent the maintained planner
contract reliably.

**Target:** Port the two reusable provider-schema projections without changing
the original Pydantic validation contract. Publish one clean Inside Success
commit that DIGIMON can pin and reproduce outside the editable workspace.

**Why:** DIGIMON Plan #179 and Plan #36 require a portable, exact dependency
revision. A local checkout passing while the declared Git dependency lacks the
same behavior invalidates trace and capability evidence.

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.

- `CLAUDE.md` - shared runtime, planning, and verification rules.
- `llm_client/execution/responses_runtime.py` - strict provider-schema helpers.
- `llm_client/execution/structured_runtime.py` - sync/async native schema paths.
- `tests/test_structured_runtime.py` - provider request and local validation controls.
- `docs/adr/0001-model-identity-v0.md` - requested, resolved, and executed
  model identity must remain exact through native-schema execution.
- `docs/adr/0002-routing-config-precedence.md` - explicit caller routing and
  fallback policy remain authoritative.
- `docs/adr/0003-warning-taxonomy.md` - provider schema rejection remains a
  typed execution failure rather than an advisory.
- `docs/adr/0004-result-model-semantics-migration.md` - terminal executed-model
  semantics must not change through this provider projection.
- `docs/adr/0009-long-thinking-background-polling.md` - Responses background
  polling is unchanged and outside this native-schema fix.
- `docs/adr/0010-cross-project-runtime-substrate.md` - provider normalization
  belongs in the shared runtime rather than DIGIMON.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` - the
  original local contract and provider request projection must remain
  diagnosable at the call boundary.
- Personal upstream commits `9cda96ba685d91af4438e42b19d54a30c4f67579`
  (PR #81) and `c90915bb18199e0cec0b2192e7138295490751a9`
  (PR #89).
- DIGIMON traces `digimon.luna_dual_role.planner.medium.20260724`
  (old runtime failure) and
  `digimon.luna_dual_role.planner.medium.fixed_pr89.20260724`
  (same counterexample passing).

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.

- `llm_client/execution/responses_runtime.py` (modify)
- `llm_client/execution/structured_runtime.py` (modify)
- `llm_client/core/client.py` (modify; compatibility re-exports)
- `tests/test_structured_runtime.py` (modify)
- `docs/API_REFERENCE.md` (generated)
- `docs/API_REFERENCE.html` (generated)
- `docs/adr/0001-model-identity-v0.md` (verification context)
- `docs/adr/0002-routing-config-precedence.md` (verification context)
- `docs/adr/0003-warning-taxonomy.md` (verification context)
- `docs/adr/0004-result-model-semantics-migration.md` (verification context)
- `docs/adr/0009-long-thinking-background-polling.md` (verification context)
- `docs/adr/0010-cross-project-runtime-substrate.md` (verification context)
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` (verification context)
- `docs/plans/106_port-ref-safe-openrouter-schemas-to-inside-success.md` (modify)
- `docs/plans/CLAUDE.md` (generated index update)

---

## Plan

### Steps

1. Port the upstream schema projection helpers exactly: preserve structural
   contracts, remove unsupported value constraints, and rewrite only provably
   disjoint discriminated unions.
2. Use the OpenAI strict Pydantic normalizer for OpenRouter native schemas so
   `$ref` siblings are resolved without losing descriptions.
3. Cover sync and async paths, multi-action unions, single-action refs,
   unsupported value constraints, and local-validation negative controls.
4. Run the exact DIGIMON Luna counterexample from a clean package built from
   the candidate commit, with fallback disabled.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_structured_runtime.py` | `test_openrouter_schema_projection_preserves_structural_contract_and_local_validation` | Provider projection removes unsupported value constraints while local validation stays exact. |
| `tests/test_structured_runtime.py` | `test_openrouter_native_schema_inlines_nested_ref_siblings` | Sync OpenRouter request does not contain `$ref` plus a sibling description. |
| `tests/test_structured_runtime.py` | `test_openrouter_async_native_schema_inlines_nested_ref_siblings` | Async OpenRouter path uses the same schema. |
| `tests/test_structured_runtime.py` | `test_openrouter_planner_call_sends_disjoint_union_as_any_of` | Disjoint planner actions retain exact acceptance semantics through `anyOf`. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_client.py -k structured` | Public structured facade remains compatible. |
| `tests/test_structured_runtime.py` | Existing cache, retry, lifecycle, and capability failures remain intact. |

---

## Acceptance Criteria

- [ ] Provider projection changes only a private schema copy.
- [ ] Original Pydantic response model remains the local validation authority.
- [ ] Sync and async unit tests pass with positive and negative controls.
- [ ] Original DIGIMON Luna single-action failure passes from the clean
      candidate revision with no fallback.
- [ ] Ruff, focused mypy, plan validation, and whitespace checks pass.
- [ ] Reviewed PR lands on `Inside-Success/llm_client` before DIGIMON advances
      its pin.

---

## Notes

- This is a downstream release port of already-merged reusable upstream
  behavior, not a new company-specific implementation.
- Do not weaken schemas globally or remove assertive `$ref` siblings.
- Do not use the workspace editable checkout as package-release evidence.
- Focused verification before the live canary:
  `tests/test_structured_runtime.py` (10 passed),
  `tests/test_client.py -k structured` (27 passed), Ruff passed, plan validation
  passed, and `git diff --check` passed. A dependency-following mypy invocation
  reaches two pre-existing `no-any-return` findings in
  `llm_client/parsing_utils.py`; the changed runtime files are checked
  separately without following imports.
