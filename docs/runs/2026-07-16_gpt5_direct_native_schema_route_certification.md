# Direct GPT-5 Native-Schema Route Certification

**Observed:** 2026-07-16
**Source revision:** `68426c2caaed3364802b72d8bd0113886fe6a131` before Plan 107 routing changes
**Profile:** direct model backend, strict native JSON Schema
**Prompt:** `llm_client/prompts/llm_test_judge.yaml`
**Schema:** `llm_client.testing.JudgeResponse`

## Question

Can OpenAI direct GPT-5 routes accept a strict native JSON-schema request and
return content that validates against the typed response model?

## Controls

- `LLM_CLIENT_OPENROUTER_ROUTING=off` so bare GPT-5 ids reach OpenAI Responses
  API instead of the default OpenRouter proxy.
- `StructuredOutputPolicy(mode="require_native_json_schema")` so Instructor,
  agent-SDK, and text fallbacks are forbidden.
- `num_retries=0`; each result is one provider attempt.
- Both calls used the same YAML prompt, response schema, and one deterministic
  criterion: "States that the sky appears blue."

## Results

| Requested / resolved model | Trace ID | Outcome | Cost |
|---|---|---|---|
| `gpt-5.6` / `gpt-5.6` | `llm_client/gpt56-direct-native-schema-certification/v3` | Success: one typed verdict, `passed=true` | `$0.002845` |
| `gpt-5.6-terra` / `gpt-5.6-terra` | `llm_client/gpt56-terra-direct-native-schema-certification/v1` | Success: one typed verdict, `passed=true` | `$0.0014225` |
| `gpt-5.5` / `gpt-5.5` | `llm_client/gpt55-direct-native-schema-recheck/v1` | Success: one typed verdict, `passed=true` | `$0.00403` |

The earlier bare `gpt-5.6` request under default routing instead resolved to
`openrouter/openai/gpt-5.6` and failed before dispatch because that proxy route
was not schema-capable. That is route-specific evidence, not a direct OpenAI
model failure.

## Disposition

`gpt-5.6` and `gpt-5.6-terra` are **contract-tested direct routes** for this
small strict-schema shape. Plan 107 registers them as explicit manual choices
and preserves that direct route under the normal routing policy. This does not
certify semantic quality, other schemas, GPT-5.6 Luna, or an automatic tier
default.

## Plan 107 Normal-Routing Verification

**Source revision:** `ca0c798` (Plan 107 route implementation)

| Requested / resolved model | Trace ID | Outcome | Cost |
|---|---|---|---|
| `gpt-5.6` / `gpt-5.6` | `llm_client/gpt56-direct-native-schema-certification/v4-plan107` | Success: one typed verdict, `passed=true`; `routing_policy=openrouter_on` preserved the direct model | `$0.002845` |

This is the end-to-end route proof: Plan 107's exact direct-provider alias is
selected before the broad `gpt-*` OpenRouter policy, so a normal configured
request reaches the certified direct Responses API path.
