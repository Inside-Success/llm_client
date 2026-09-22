# Plan #365: OpenRouter Flex Service Tier

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** lower-cost synchronous Luna coding-agent execution

---

## Gap

**Current:** OpenRouter's normalized `service_tier` parameter can enter through
untyped provider kwargs, but `llm_client` does not declare it as a supported
normalized control, cannot express Flex through its typed route policy, and
does not retain the served tier in call results or observability.

**Target:** `OpenRouterRoutePolicyV1(service_tier="flex")` compiles to the
documented synchronous OpenRouter Flex request, requires endpoint parameter
support, rejects contradictory raw tier controls, and records the provider-
reported served tier in the result, routing trace, JSONL, and SQLite.

**Why:** Luna Flex is currently priced at half the standard token rates, but the
savings are only operationally safe when selection cannot be silently dropped
and the tier returned by the provider remains queryable.

---

## References Reviewed

- `CLAUDE.md`, package/subtree instructions, and `docs/plans/TEMPLATE.md`.
- `roadmap/codebase/wiki/{index.md,concepts/model-selection-and-routing.md,concepts/observability-and-budgets.md,workflows/text-call-lifecycle.md}`.
- `llm_client/execution/call_contracts.py` — typed OpenRouter policy.
- `llm_client/utils/openrouter.py` — normalized-control and fail-loud routing seam.
- `llm_client/core/data_types.py`, `llm_client/core/client_dispatch.py`, and
  `llm_client/io_log.py` — result finalization and durable call evidence.
- ADRs 0002, 0003, 0007, 0010, 0014, and 0016.
- Plans 104, 110, 117, 336, 347, and 348.
- Current OpenRouter service-tier, model, and pricing documentation; installed
  LiteLLM 1.97.0 normalization behavior.
- Thirty-day local SQLite evidence for OpenRouter Luna usage.

---

## Files Affected

- `llm_client/execution/call_contracts.py`
- `llm_client/utils/openrouter.py`
- `llm_client/core/data_types.py`
- `llm_client/schemas.py`
- `llm_client/core/client_dispatch.py`
- `llm_client/io_log.py`
- `tests/test_openrouter_route_policy.py`
- `tests/test_provider_kwargs.py`
- `tests/test_io_log.py`
- `docs/guides/model-selection.md`
- `docs/adr/0007-observability-contract-boundary.md`
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- generated API reference and plan index

---

## Plan

### Steps

1. Add a Flex-only typed tier to `OpenRouterRoutePolicyV1`.
2. Compile it to top-level `service_tier="flex"`, declare it through
   LiteLLM's normalized-parameter compatibility seam, and reject raw conflicts.
3. Extract bounded provider-reported tier evidence during result finalization.
4. Persist the served tier additively in JSONL and migrated/fresh SQLite.
5. Add deterministic transport, result, migration, and import tests.
6. Update the route guide, ADRs, generated API docs, and repository checks.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_openrouter_route_policy.py` | Flex policy validation/compilation cases | Only the governed Flex value is accepted and raw tier ambiguity fails locally |
| `tests/test_provider_kwargs.py` | Flex sync/async payload cases | Exact tier forwarding, `allowed_openai_params`, and `require_parameters=true` |
| `tests/test_result_finalization.py` | provider tier extraction cases | Served tier reaches result and routing evidence without inventing absent data |
| `tests/test_io_log.py` | fresh/migrated/import tier cases | Served tier is durable and queryable across compatibility paths |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_openrouter_route_policy.py` | Existing provider/cache policy remains stable |
| `tests/test_provider_kwargs.py` | Existing OpenRouter transport controls remain stable |
| `tests/test_result_finalization.py` | Identity/cache finalization remains stable |
| `tests/test_io_log.py` | JSONL/SQLite compatibility remains stable |

---

## Acceptance Criteria

- [ ] Typed Flex policy reaches OpenRouter on sync, async, structured, and stream paths.
- [ ] LiteLLM/OpenRouter cannot silently discard the tier control.
- [ ] Contradictory raw `service_tier` plus typed policy fails before dispatch.
- [ ] Provider-reported served tier is exposed on `LLMCallResult` and routing trace.
- [ ] Fresh and migrated SQLite schemas plus JSONL import retain served tier.
- [ ] Call snapshot/replay identity retains the typed request policy.
- [ ] Focused tests, lint, API generation, relationship validation, and feasible broader tests pass.

---

## Notes

- This is the synchronous Flex tier, not OpenRouter's asynchronous Batch API.
- The typed surface intentionally exposes only `flex`; it does not add paid
  priority tiers or provider-default selection under the same cost-saving control.
- Missing provider-reported tier remains `None`; the client does not guess.
