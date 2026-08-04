# Typed OpenRouter Route Policy Probe — 2026-07-27

**Purpose:** Non-private acceptance evidence for Plan #336's shared-client
route-policy slice. This is not private-data authorization evidence.

## Frozen public input

- Requested model: `openrouter/deepseek/deepseek-v4-flash`
- Prompt: `Return the integer value 1.`
- Response schema: `RoutePolicyProbeV1(value: int)`
- Structured-output policy: `require_native_json_schema`
- Route policy: `data_collection="deny"`, `zero_data_retention=true`,
  provider fallback permitted, and no provider allowlist.
- Retry count: `0`

## Observed result

The call returned `{"value": 1}` and local Pydantic validation succeeded.
The authenticated OpenRouter generation-evidence reader was then allowed to
observe the selected upstream route after the call; it did not select or alter
that route.

| Field | Observed value |
| --- | --- |
| Requested model | `openrouter/deepseek/deepseek-v4-flash` |
| Resolved model | `openrouter/deepseek/deepseek-v4-flash-20260423` |
| Upstream provider | `Fireworks` |
| Upstream endpoint | `955a2bd9-841c-4cec-a92e-dbfd93111b24` |
| Outcome | `parseable` |
| Failure stage | `none` |
| Route observation | `routeobs1_c66946ec710611805c9d8489` |
| Trace | `llm-client/plan-336/nonprivate-probe-v2` |

The generation metadata became available after four bounded 404 retries. Those
were metadata-read retries only; the model call itself ran once.

## Scope boundary

This observation establishes that the new typed policy reaches a compatible
OpenRouter upstream for this fixed model and public input. It does not
authorize Fireworks, or any other provider, to process private Slack content.
The Inside Success consumer must supply an explicit authorization-compatible
allowlist before it transmits private source fields.
