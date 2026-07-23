# Plan #111: Bound provider schema names

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Inside Success five-person Deep retrieval beta

---

## Gap

**Current:** Native structured calls forward `response_model.__name__`
unchanged. Dynamic Pydantic models can exceed OpenAI's 64-character schema-name
limit.

**Target:** All native structured paths preserve short names and
deterministically shorten overlong names without changing the local schema or
validation contract.

**Why:** The hosted Inside Success Deep trace completed evidence retrieval but
failed during final coverage because its schema name was 70 characters.

---

## References Reviewed

- `llm_client/execution/structured_runtime.py:760-930` - synchronous native transports.
- `llm_client/execution/structured_runtime.py:1540-1730` - asynchronous native transports.
- `docs/adr/0001-model-identity-v0.md` - model identity remains unchanged.
- `docs/adr/0002-routing-config-precedence.md` - routing precedence remains unchanged.
- `docs/adr/0003-warning-taxonomy.md` - provider rejection remains fail-loud.
- `docs/adr/0004-result-model-semantics-migration.md` - result model semantics remain unchanged.
- `docs/adr/0009-long-thinking-background-polling.md` - Responses polling remains unchanged.
- `docs/adr/0010-cross-project-runtime-substrate.md` - shared structured transport ownership.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` - call contracts remain replayable with bounded transport metadata.
- `investigations/2026-07-23-openai-structured-schema-name-limit.md` - runtime evidence and root cause.

---

## Files Affected

- `llm_client/execution/structured_runtime.py` (modify)
- `tests/test_structured_runtime.py` (modify)
- `docs/plans/111_bound_provider_schema_names.md` (create)
- `investigations/2026-07-23-openai-structured-schema-name-limit.md` (create)

---

## Plan

1. Add one deterministic provider-schema-name helper.
2. Use it in synchronous/asynchronous Responses and Completions paths.
3. Prove short-name preservation, maximum length, and collision resistance.
4. Run focused structured-runtime tests and the exact hosted Deep request.

---

## Required Tests

| Test File | Test Function | What It Verifies |
| --- | --- | --- |
| `tests/test_structured_runtime.py` | `test_provider_schema_name_preserves_short_names` | Compatible names remain unchanged. |
| `tests/test_structured_runtime.py` | `test_provider_schema_name_bounds_long_names_without_collisions` | Long names are at most 64 characters and same-prefix names remain distinct. |

## Acceptance Criteria

- [x] Focused structured-runtime tests pass.
- [x] Existing structured runtime tests remain green.
- [x] A real direct Terra call accepts an overlong response-model name.
- [ ] The hosted Inside Success Deep request passes its final coverage call.
