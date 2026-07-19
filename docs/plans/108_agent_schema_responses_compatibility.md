# Plan #108: Agent-schema Responses compatibility

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cybernetic simulator evidence regeneration with a direct structured route

## Gap

**Current:** Plan 107 preserves direct GPT-5.6 provider identity but omits those
identifiers from the independent Responses transport detector. The Responses
runtime also hand-normalizes Pydantic schemas and leaves `$ref` siblings that
OpenAI rejects, even though the installed OpenAI SDK already normalizes them.

**Target:** Registered direct GPT-5.6 aliases use Responses, and Responses
requests use the SDK's strict Pydantic normalizer. Provider-incompatible
`oneOf` remains a caller-schema concern; the runtime must not silently weaken it.

**Why:** One real simulator contract passed after only literal-disjoint
`oneOf`→`anyOf` at the consumer boundary and SDK strict normalization. Shared
transport compatibility belongs here; domain schema design does not.

## References Reviewed

- `llm_client/core/model_detection.py:21-79` — closed Responses model set.
- `llm_client/core/provider_policy.py:182-197` — direct GPT-5.6 aliases.
- `llm_client/execution/responses_runtime.py:52-72` — current hand normalizer.
- OpenAI SDK `openai.lib._pydantic.to_strict_json_schema` — installed provider
  normalizer that resolves `$ref` siblings and removes unsupported defaults.
- ADRs 0001, 0002, 0003, 0004, 0009, 0010, and 0014 — required route,
  execution, failure, identity, and replay boundaries.

## Files Affected

- `llm_client/core/model_detection.py`
- `llm_client/core/client.py`
- `llm_client/execution/responses_runtime.py`
- `llm_client/execution/structured_runtime.py`
- `tests/test_client.py`
- `tests/test_structured_runtime.py`
- `docs/plans/CLAUDE.md`

## Plan

1. Add both registered GPT-5.6 direct identifiers to Responses detection.
2. Wrap the installed OpenAI strict-schema normalizer for Responses requests.
3. Prove `$ref` siblings are inlined without losing field descriptions, and
   prove provider-prefixed routes remain non-Responses.
4. Run the exact downstream one-turn composition probe before licensing use.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_client.py` | `TestResponsesAPIDetection::test_gpt56_direct_models_use_responses_api` | both direct aliases select Responses; prefixed aliases do not |
| `tests/test_structured_runtime.py` | `test_openai_responses_schema_inlines_ref_siblings` | nested field descriptions survive inlining and no illegal `$ref` sibling remains |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_structured_runtime.py` | structured execution paths remain coherent |
| `tests/test_client.py` | existing route behavior remains intact |

## Acceptance criteria

- Focused tests and type/lint checks pass.
- Exact downstream `AgentStepResult` one-turn run completes with one terminal
  outcome and durable trace identity.
- No model fallback, response-contract weakening, or scenario model change is
  hidden inside this shared-runtime repair.

## Completion evidence

- `pytest` focused controls: 22 Responses-detection and structured-runtime
  tests passed.
- Focused strict mypy: no issues in the model detector and Responses helper.
- Exact downstream composition at simulator commit `3958705` plus its
  uncommitted literal-disjoint union change: three `gpt-5.6` agent calls,
  three typed `AgentStepResult` events, one `RunCompleted`, no `RunFailed`,
  trace prefix
  `cybernetic_influence_v2/gpt56-exact-agent-schema-certification/20260718-v1`,
  observed cost `$0.04510`.
