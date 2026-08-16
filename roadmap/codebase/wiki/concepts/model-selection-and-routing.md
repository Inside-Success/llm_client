---
type: concept
title: Model Selection and Routing
description: The distinction between task-based selection, call-plan resolution, execution policy, transports, retries, and fallbacks.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../llm_client/core/model_selection.py, ../../../../llm_client/core/client_dispatch.py, ../../../../llm_client/core/routing.py, ../../../../llm_client/execution/execution_kernel.py]
confidence: high
---

# Two decisions, not one

Task-based model selection and per-call routing are related but separate.
`resolve_model_selection` chooses a requested model for a task using registry,
override, availability, and optional performance information. Once a call has
a requested model, `_resolve_call_plan` applies configuration-based
normalization, model-execution policy, deprecation checks, temporary
unavailability, and the caller’s fallback list to produce an ordered execution
chain and routing trace.

The text runtime then validates the execution-mode contract and dispatches each
candidate through one of the supported route families: an agent SDK, the
Responses path, or chat completions. Shared execution-kernel functions govern
retries within a candidate and fallback between candidates. A fallback is
therefore a controlled transition in an explicit model chain, not a silent
provider substitution.

# Where to edit

- Model registry/task choice: `core/models.py` and `core/model_selection.py`.
- Normalization and call-plan construction: `core/routing.py` and
  `core/client_dispatch.py`.
- Allow/deny/justification policy: `core/model_execution_policy.py`.
- Retryability and backoff: `execution/retry.py`.
- Shared attempt/fallback loops: `execution/execution_kernel.py`.
- Provider-specific normalization: completion/Responses runtimes and
  `utils/openrouter.py`.

See [Text-call lifecycle](../workflows/text-call-lifecycle.md) for the composed
path and [Observability and budgets](observability-and-budgets.md) for the
routing evidence returned and stored.

# Citations

1. [`resolve_model_selection`, lines 38–68](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/core/model_selection.py#L38-L68)
2. [`_resolve_call_plan`, lines 101–166](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/core/client_dispatch.py#L101-L166)
3. [Shared retry/fallback kernel](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/execution/execution_kernel.py#L72-L290)
