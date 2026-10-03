---
type: concept
title: Model Selection and Routing
description: The distinction between task-based selection, call-plan resolution, execution policy, transports, retries, and fallbacks.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/core/model_selection.py, ../../../../llm_client/core/client_dispatch.py, ../../../../llm_client/core/routing.py, ../../../../llm_client/execution/execution_kernel.py, ../../../../llm_client/inside_success_policy.py, ../../../../llm_client/core/model_execution_policy.py, ../../../../llm_client/execution/retry.py]
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

# Company model-policy overlay

The execution allowlist is composed, not hand-edited. `core/model_execution_policy.py`
defines `SHARED_EXECUTION_MODELS` (the generic set inherited from the former
upstream) and sets `ALLOWED_EXECUTION_MODELS = SHARED_EXECUTION_MODELS |
INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS`. The second set lives in
`inside_success_policy.py` (new since `4f7ecfa`), which lists 16 exact
`claude-code/`, `codex/`, and `openrouter/` routes plus a machine-readable
acceptance record naming Brian Mills as approver. `inside_success_policy.py`
also lists 8 routes (`INSIDE_SUCCESS_HARD_BLOCK_EXCEPTIONS`) that
`execution/call_contracts.py` adds to `_DEPRECATED_MODEL_EXCEPTIONS`, so they
are not flagged by the generic retirement patterns. The module comments state
why the union is kept separate: merging this overlay into the generic upstream
would silently relax ADR 0016 decision 5 and Plan #348.

# Retry classification and logging

`execution/retry.py::_is_retryable` treats `LLMProviderResponseError` (a failed
generation reported as a successful response; see
[Structured output](structured-output.md)) as always retryable, and
`_compute_retry_delay` labels its delay source `provider` when no provider
delay hint exists. `_retry_error_summary` produces the one-line error text used
by retry logs in `execution/execution_kernel.py` and `utils/openrouter.py`: for
litellm's `JSONSchemaValidationError` it logs the class, schema title, and a
120-character raw-response snippet instead of the full schema; other errors are
whitespace-collapsed and capped at 240 characters. Kernel retry lines now also
include `model=` and, when known, `task=`.

# Where to edit

- Model registry/task choice: `core/models.py` and `core/model_selection.py`.
- Normalization and call-plan construction: `core/routing.py` and
  `core/client_dispatch.py`.
- Allow/deny/justification policy: `core/model_execution_policy.py`; company-only routes: `inside_success_policy.py`.
- Retryability and backoff: `execution/retry.py`.
- Shared attempt/fallback loops: `execution/execution_kernel.py`.
- Provider-specific normalization: completion/Responses runtimes and
  `utils/openrouter.py`.

See [Text-call lifecycle](../workflows/text-call-lifecycle.md) for the composed
path and [Observability and budgets](observability-and-budgets.md) for the
routing evidence returned and stored.

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [`resolve_model_selection`, lines 196-226](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/model_selection.py#L196-L226)
2. [`_resolve_call_plan`, lines 101-189](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/client_dispatch.py#L101-L189)
3. [Shared retry/fallback kernel, lines 73-356](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/execution_kernel.py#L73-L356)
4. [Allowlist composition, lines 40-90](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/model_execution_policy.py#L40-L90)
5. [Company overlay](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/inside_success_policy.py#L1-L57)
6. [Deprecation exceptions, lines 1010-1018](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_contracts.py#L1010-L1018)
7. [Retry summary and classification, lines 108-137 and 310-323](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/retry.py#L108-L137)
