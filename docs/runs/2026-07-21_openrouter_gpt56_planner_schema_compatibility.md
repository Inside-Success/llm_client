# OpenRouter GPT-5.6 planner-schema compatibility — 2026-07-21

## Decision

GPT-5.6 Terra and Luna are registered as explicit OpenRouter planner
candidates. Terra is the preferred DIGIMON graph-planner candidate; Luna is a
lower-latency candidate for simpler bounded decisions. Neither becomes a
shared tier default from this evidence alone.

## Real contract exercised

The retained input was DIGIMON call `13449946` from trace
`digimon.query.394c4e7c1dc044f88dcedd32e6b965ab`, task
`digimon.query.dynamic_plan`. It contained the real planner system prompt,
89,623-character user context, and the captured
`PlannerRuntimeEnvelope_1457d37e879b_stop` schema.

The unmodified Pydantic provider schema failed on both OpenRouter routes before
generation because the endpoint rejected `oneOf` under `decision`. The planner
union is discriminated by required, mutually exclusive `action` constants.
Projecting that one union to `anyOf` preserves its accepted values while local
Pydantic validation continues to use the original contract.

## Results

| Route | Trace | Wall time | Tokens | Cost | Result |
|---|---|---:|---:|---:|---|
| `openrouter/openai/gpt-5.6-terra` (medium) | `digimon.model_compatibility.terra-medium.anyof.20260721` | 9.439 s | 34,849 in / 198 out | $0.11187125 | Provider JSON and original local schema valid; selected `relationship.vdb` with a relevant Shipping query. |
| `openrouter/openai/gpt-5.6-luna` (medium) | `digimon.model_compatibility.luna-medium.anyof.20260721` | 4.321 s | 34,849 in / 467 out | $0.0463625 | Provider JSON and original local schema valid; selected `structured.cypher` with a relevant roster-evidence rationale. |
| `openrouter/openai/gpt-5.6-terra` (medium), normal `acall_llm_structured` path | `llm_client.gpt56_terra.discriminated_union.runtime.20260721` | 4.696 s | retained in observability | $0.0011675 | Runtime projected the provider schema, returned `search`, and validated the unchanged local discriminated union. |

The runtime repair rewrites only a `oneOf` whose branches provably require one
common property with unique literal values. Overlapping or unproven unions are
left unchanged and therefore still fail visibly if a provider cannot accept
them.

## Current external metadata

- [OpenRouter Terra](https://openrouter.ai/openai/gpt-5.6-terra): 1M context,
  $2.50/M input and $15/M output.
- [OpenRouter Luna](https://openrouter.ai/openai/gpt-5.6-luna-20260709): 1M
  context, $1/M input and $6/M output.
- Artificial Analysis snapshot reviewed 2026-07-21: Terra medium intelligence
  46, 121 output tokens/s, 1.35 s time to first token; Luna medium intelligence
  38, 192 output tokens/s, 1.75 s time to first token. These are selection
  inputs, not local route certification.

## Scope of evidence

This proves transport and local structural compatibility for one retained,
large DIGIMON planner contract, plus the ordinary `acall_llm_structured`
execution path on a small discriminated union. It does not prove general
semantic superiority, all JSON Schema shapes, every OpenRouter upstream
provider, or full-query latency. A normal full DIGIMON planner trace is still
required before DIGIMON calls the selected route deployment-verified.
