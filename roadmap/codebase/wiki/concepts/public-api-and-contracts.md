---
type: concept
title: Public API and Contracts
description: How stable entrypoints, required metadata, typed results, and internal runtimes divide responsibility.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/__init__.py, ../../../../llm_client/core/client.py, ../../../../llm_client/execution/call_contracts.py, ../../../../llm_client/execution/call_wrappers.py, ../../../../llm_client/core/data_types.py]
confidence: high
---

# Public surface

Consumers normally import from `llm_client`, which re-exports the stable
facades defined in `core/client.py`. The main families are synchronous and
asynchronous text calls, Pydantic-validated structured calls, tool calls,
batches, streaming, and embeddings. `LLMCallResult` carries response content,
usage, cost, requested/resolved model identity, routing trace, tool calls,
warnings, and cache state. Transport-specific evidence remains additive: direct
Codex CLI calls expose normalized completed items as `codex_events` and the
exact nonblank decoded stdout stream as `codex_jsonl`. The latter exists so
experiment controllers can reject malformed or unknown envelopes without
mistaking a filtered projection for the complete stream.

Every maintained call is governed by task, trace, and budget metadata. The
public wrapper normalizes those values, acquires a budget scope, starts
lifecycle observation, and passes provider-safe arguments into the selected
runtime. For `codex` and `codex/*` models the envelope also calls
`resolve_codex_account_identity`, which stores an opaque account digest in the
envelope; see [Observability and budgets](observability-and-budgets.md). The public signature therefore owns the caller contract; internal
modules own how the contract is executed.

# Change routing

| Change | Begin at |
| --- | --- |
| Add or alter a consumer-facing call parameter | `core/client.py` and call-contract tests |
| Change required metadata or budget semantics | `execution/call_contracts.py` and `call_wrappers.py` |
| Change timeout behavior | `execution/timeout_policy.py` (`LLM_CLIENT_TIMEOUT_POLICY`); structured facades skip the library default timeout when the policy bans timeouts |
| Change model/provider selection | [Model selection and routing](model-selection-and-routing.md) |
| Change structured validation | [Structured output](structured-output.md) |
| Add evidence/query behavior | [Observability and budgets](observability-and-budgets.md) |

Read the [text](../workflows/text-call-lifecycle.md) or
[structured](../workflows/structured-call-lifecycle.md) workflow before
editing a cross-cutting call path.

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [Package public facade, `__init__.py`](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/__init__.py)
2. [`call_llm` contract, lines 463-595](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/client.py#L463-L595)
3. [Public-call envelope, lines 48-153](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_wrappers.py#L48-L153)
4. [`LLMCallResult` evidence fields, lines 29-98](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/data_types.py#L29-L98)
5. [Timeout policy, lines 20-154](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/timeout_policy.py#L20-L154)
6. [Required-tag contract](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_contracts.py)
