---
type: concept
title: Public API and Contracts
description: How stable entrypoints, required metadata, typed results, and internal runtimes divide responsibility.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../llm_client/__init__.py, ../../../../llm_client/core/client.py, ../../../../llm_client/execution/call_contracts.py]
confidence: high
---

# Public surface

Consumers normally import from `llm_client`, which re-exports the stable
facades defined in `core/client.py`. The main families are synchronous and
asynchronous text calls, Pydantic-validated structured calls, tool calls,
batches, streaming, and embeddings. `LLMCallResult` carries response content,
usage, cost, requested/resolved model identity, routing trace, tool calls,
warnings, and cache state.

Every maintained call is governed by task, trace, and budget metadata. The
public wrapper normalizes those values, acquires a budget scope, starts
lifecycle observation, and passes provider-safe arguments into the selected
runtime. The public signature therefore owns the caller contract; internal
modules own how the contract is executed.

# Change routing

| Change | Begin at |
| --- | --- |
| Add or alter a consumer-facing call parameter | `core/client.py` and call-contract tests |
| Change required metadata or budget semantics | `execution/call_contracts.py` and `call_wrappers.py` |
| Change model/provider selection | [Model selection and routing](model-selection-and-routing.md) |
| Change structured validation | [Structured output](structured-output.md) |
| Add evidence/query behavior | [Observability and budgets](observability-and-budgets.md) |

Read the [text](../workflows/text-call-lifecycle.md) or
[structured](../workflows/structured-call-lifecycle.md) workflow before
editing a cross-cutting call path.

# Citations

1. [Package public facade](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/__init__.py#L1-L62)
2. [`call_llm` contract](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/core/client.py#L454-L585)
3. [Public-call envelope](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/execution/call_wrappers.py#L65-L127)
