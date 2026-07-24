# Plan #118: OpenRouter Discriminated-Union Projection

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** DoDAF Plan 75 Army publication extraction

---

## Gap

**Current:** The OpenRouter projection proves a Pydantic `oneOf` union has
disjoint required literal branches and rewrites it to provider-compatible
`anyOf`, but leaves the `discriminator` annotation attached. OpenRouter's
Anthropic, Azure, and Bedrock routes reject that exact combination before
generation.

**Target:** When and only when the existing proof permits `oneOf` to become
`anyOf`, remove the now-invalid `discriminator` annotation from the private
provider copy. Continue validating against the original discriminated Pydantic
model.

**Why:** Provider-only annotations must not prevent a valid typed contract from
executing. The fix belongs in the shared transport owner, not a DoDAF-specific
extractor.

---

## References Reviewed

- `llm_client/execution/responses_runtime.py` - OpenRouter schema projection.
- `tests/test_structured_runtime.py` - provider projection and local validation.
- `docs/adr/0010-cross-project-runtime-substrate.md` - shared transport ownership.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` - original
  call snapshot remains replay authority.
- DoDAF traces `onto_canon6.extract.57dfe2c229b407c4` and
  `onto_canon6.extract.07118cf765271326` - rejected and successful schemas.
- OpenAI Structured Outputs guide - provider schemas have explicit size limits.

---

## Boundaries And Business Rules

- The caller-facing response model and call signature do not change.
- The call snapshot retains the original Pydantic schema.
- Only the rewritten union in the private provider copy loses
  `discriminator`; every branch retains its required unique `const`.
- Local Pydantic validation remains the final typed-boundary authority.
- Direct-provider and non-structured paths are unchanged.
- An unconstrained schema still fails loud.

## Files Affected

- `llm_client/execution/responses_runtime.py` (modify)
- `tests/test_structured_runtime.py` (modify)
- `docs/plans/118_openrouter_schema_compaction.md` (create)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Add a failing projection test for removal of the invalid annotation.
2. Remove `discriminator` only alongside the proven `oneOf` to `anyOf` rewrite.
3. Run focused structured-runtime tests and the exact failed DoDAF schema.
4. Merge and pin the revision in DoDAF.

---

## Required Tests

| Test | What It Verifies |
|---|---|
| `test_provider_projection_rewrites_only_disjoint_literal_union` | Rewritten provider union has `anyOf`, unique literal branches, and no unsupported discriminator annotation |
| `tests/test_structured_runtime.py` | Neighboring sync/async provider behavior remains compatible |
| exact DoDAF pages 47-49 singleton replay | The previously rejected real union reaches native generation and validates after projection |

---

## Acceptance Criteria

- [x] A proven disjoint union reaches OpenRouter as `anyOf` without
  `discriminator`.
- [x] Unique required literal branches and all other structural constraints
  remain.
- [x] The original Pydantic model still rejects invalid values locally.
- [x] Focused tests and lint pass. Focused mypy reaches an inherited
  `no-any-return` error at `responses_runtime.py:88`, unchanged from `main`.
- [x] Exact DoDAF trace `onto_canon6.extract.b7163589ab78f8ce` reaches native
  Opus generation and returns 12 schema-valid
  `activityPerformedByPerformer` candidates.

## Concerns And Stop Conditions

- Arbitrary or overlapping `oneOf` contracts must remain unchanged and fail
  visibly if unsupported.
- Provider success on one schema is a bounded compatibility result, not a
  universal route certification. Multi-predicate Anthropic grammars remain too
  large and are a separate onto-canon response-schema design boundary.
- Stop if the trace snapshot or direct-provider schema is modified.
