# OpenRouter GPT-5.6 Sol authoring-schema certification

Date: 2026-07-25

## Claim

`openrouter/openai/gpt-5.6-sol` is an explicitly selectable OpenRouter route
for the Cybernetic Influence typed scenario-authoring contract. This evidence
licenses transport and schema compatibility only; it does not assert scenario
quality or make the route an automatic default.

## Environment and invalidation inputs

- Source branch: `feature/openrouter-sol-route`.
- Shared client revision: `0a6d0268d62443499e9ef8cc5208a00ef4573a90`.
- Provider catalog: authenticated `GET https://openrouter.ai/api/v1/models`,
  observed 2026-07-25; the returned model supports `structured_outputs` and
  `reasoning_effort`.
- Contract: Cybernetic Influence `_ProposalConsumer` JSON schema
  `526b57cae5d9108c`.
- Target: local shared-client runtime with the caller's OpenRouter credential.

## Direct contract evidence

| Requested and executed route | Trace | Result | Observed cost |
|---|---|---|---:|
| `openrouter/openai/gpt-5.6-sol` | `cybernetic_influence_v3/authoring/openrouter-sol-certification/20260725` | Native `json_schema` response validated as `resource_request_v1`; no unresolved question | `$0.046620` |

The retained `llm_calls` row records `execution_path=native_schema`, one
successful terminal lifecycle, 1,911 prompt tokens, 1,156 completion tokens,
and 395 reasoning tokens. The returned draft was compiled by the downstream
authoring consumer.

## Negative controls

- Before this route was registered, the exact requested identity failed closed
  at the execution allowlist; it could not silently fall back to direct OpenAI.
- The policy tests reject unlisted models, omitted reasoning for governed
  routes, and unsupported reasoning before provider dispatch.

## Scope

The current evidence is valid only while the exact route, schema, client
source, and OpenRouter credentials remain usable. Any change to those inputs
requires a fresh direct contract probe before advertising the route as usable.
