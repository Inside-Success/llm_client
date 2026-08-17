# Plan #361: Compatibility-Aware Workload Route Selection

**Status:** Implemented (focused verification)
**Type:** implementation

## Decision

The second half of `subcription_vs_openrouter_deepresearch.md` changes Plan
#360's global-default conclusion. Included Codex capacity is first choice only
for declared compatible, trusted, subscription-authenticated work with known
available capacity. It is not a universal provider default.

`resolve_workload_route()` requires an explicit `WorkloadRouteContext` and
returns a model, provider classification, explicit medium reasoning effort, and
non-empty `model_justification`. Direct OpenAI API is selected for service and
managed automation requirements. OpenRouter is selected only for a declared
router-specific requirement or current recorded value comparison. Exhausted
included capacity fails until the caller declares the paid winner among Codex
credits, direct API, and OpenRouter.

## Acceptance Criteria

- [x] No new-context call can receive a universal provider default.
- [x] Compatible trusted work with available capacity resolves to Codex.
- [x] API/service and OpenRouter-specific requirements resolve explicitly.
- [x] Exhaustion cannot silently become OpenRouter overflow.
- [x] The resolved selection satisfies the shared allowlist/justification and
  reasoning contract.

## Verification

- Focused selection and execution-policy tests cover the routing matrix and
  policy integration.
- Ruff checks changed Python modules and tests.
- Generated public API references are refreshed.

## Non-Claims

- This selector does not query mutable quota, pricing, entitlement, or model
  availability data; callers declare and record those facts at the decision
  boundary.
- It does not authorize account rotation or imply that subscription capacity is
  suitable for CI/CD or public service workloads.
