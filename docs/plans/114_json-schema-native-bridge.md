# Plan #114: JSON-Schema-Native Bridge

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** learning-environment migration away from direct provider transport

---

This plan was initially allocated number 113. A concurrent mainline plan used
that number before integration, so this authority was renumbered to 114 during
the current-main merge.

## Gap

**Current:** `call_llm_structured` owns provider routing, strict-schema
projection, retries, validation repair, budgets, cost, and observability, but its
public contract requires a Python Pydantic model. Non-Python consumers can pass
`response_format` through the text API only by reimplementing schema projection
and local validation.

**Target:** Add a public sync/async JSON-Schema wrapper and a versioned stdin/stdout
CLI. The wrapper adapts an arbitrary valid JSON Schema into the existing Pydantic
structured runtime, returns the validated JSON value, and defaults to
provider-native strict execution.

**Why:** Provider execution policy belongs in `llm_client`; domain schemas and
post-generation compilation belong in consuming projects.

---

## References Reviewed

- `CLAUDE.md` - repository workflow and structured-output policy.
- `llm_client/execution/structured_runtime.py` - native schema projection,
  repair retries, attempt receipts, and strict execution.
- `llm_client/execution/responses_runtime.py` - direct OpenAI and OpenRouter
  provider-schema transformations.
- `llm_client/core/client.py` - public sync/async structured entry points.
- `llm_client/execution/call_contracts.py` - `StructuredOutputPolicy`.
- `llm_client/__main__.py` and `llm_client/cli/review_artifact.py` - CLI
  registration and handler conventions.
- `docs/plans/99_strict_native_json_schema_execution.md` - strict path contract.
- `docs/plans/104_openrouter-provider-limit-observer.md` - public JSON CLI and
  secret-free envelope precedent.
- `docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md` and
  `docs/ops/CAPABILITY_DECOMPOSITION.md` - shared-runtime ownership.

---

## Boundaries And Contracts

| Boundary | Owns | Must not own |
|---|---|---|
| Consumer | domain JSON Schema, prompts, final domain validation and compilation | provider routing, credentials, retry, schema projection |
| JSON-Schema wrapper | schema validity, dynamic Pydantic adapter, strict policy default | domain semantics |
| Existing structured runtime | provider projection, dispatch, repair retries, budget, cost, observability | consumer compilation |
| CLI | versioned JSON request/result serialization | secret values or arbitrary code loading |

The dynamic response model returns the caller's schema from
`model_json_schema()` and validates parsed values with Draft 2020-12-compatible
`jsonschema`. Validation failures become Pydantic `ValidationError`, preserving
the existing repair-retry path.

---

## Files Affected

- `pyproject.toml` (modify)
- `llm_client/json_schema.py` (create)
- `llm_client/cli/json_schema_call.py` (create)
- `llm_client/__init__.py` (modify)
- `llm_client/__main__.py` (modify)
- `tests/test_json_schema.py` (create)
- `tests/test_cli_json_schema_call.py` (create)
- `tests/test_cli_smoke.py` (modify if command inventory requires it)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate)
- `docs/plans/114_json-schema-native-bridge.md` (create/update)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Add negative-first tests for invalid schemas and locally invalid model output.
2. Add a dynamic root-model factory and sync/async wrappers over the established
   structured runtime.
3. Add a versioned stdin/stdout CLI with strict request and response envelopes.
4. Regenerate API docs and update the plan index.
5. Run focused tests, CLI smoke, type/lint checks, the full suite, and a final
   diff audit.

---

## Required Tests

| Test File | Test | What It Verifies |
|---|---|---|
| `tests/test_json_schema.py` | schema factory positive/negative | exact schema exposure and local validation |
| `tests/test_json_schema.py` | sync/async delegation | strict native policy and validated root return |
| `tests/test_cli_json_schema_call.py` | valid stdin request | stable secret-free JSON result envelope |
| `tests/test_cli_json_schema_call.py` | malformed request/call failure | nonzero fail-loud behavior without stdout corruption |
| `tests/test_cli_smoke.py` | command help | command remains discoverable without provider access |

---

## Acceptance Criteria

- [x] Arbitrary valid JSON Schema uses the existing strict structured runtime.
- [x] OpenRouter/direct-provider projection remains owned by existing
  `llm_client` code.
- [x] Local JSON Schema violations are represented as Pydantic validation errors.
- [x] CLI input and output are versioned, typed, and contain no credential field.
- [x] Sync and async APIs have parity.
- [x] Focused tests, CLI smoke, API drift, Ruff, mypy, and full tests pass.
- [x] A consumer can remove direct provider transport without reproducing
  provider schema capability logic.

---

## Non-Claims

- This does not prove semantic quality of generated content.
- This does not add a network service or remote authorization boundary.
- This does not replace consumer-side domain validation or compilation.

---

## Completion Evidence

- Focused wrapper and CLI tests: `11 passed`.
- Full repository suite after current-main integration:
  `1849 passed, 3 skipped, 12 deselected`.
- Ruff and strict mypy: passed.
- Generated API reference drift check: passed.
- Strict relationship validation and `git diff --check`: passed.
- `learning-environment` migrated its retained Plate Boundaries trial to the
  bridge; its build, 208-test suite, schema drift, docs, and package smoke
  checks passed.
- The CLI redacts environment-held secret values from runtime error messages;
  its request schema has no credential, endpoint, or provider-ID fields.
