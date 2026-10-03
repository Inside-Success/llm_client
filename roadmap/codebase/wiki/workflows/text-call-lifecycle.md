---
type: workflow
title: Text-Call Lifecycle
description: End-to-end path from call_llm through contracts, routing, attempts, transport, result finalization, and evidence.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/core/client.py, ../../../../llm_client/execution/call_wrappers.py, ../../../../llm_client/execution/text_runtime.py, ../../../../llm_client/execution/execution_kernel.py, ../../../../llm_client/execution/retry.py, ../../../../llm_client/execution/codex_identity.py]
confidence: high
---

# Flow

```text
call_llm
  -> prepare public-call envelope
  -> acquire budget scope + emit lifecycle start
  -> _call_llm_impl (sync bridge)
  -> _acall_llm_impl (single main text implementation)
  -> resolve call plan + validate execution contract
  -> for each model: retry loop
       -> agent SDK | Responses API | chat completions
       -> normalize and finalize LLMCallResult
  -> fallback to next model when policy permits
  -> emit terminal lifecycle + settle/release budget
```

# Step-by-step

1. `core/client.py::call_llm` owns the public signature. It forwards routing,
   parent-trace, and budget-scope controls into `_prepare_public_call_envelope`.
2. `call_wrappers.py` requires task/trace/budget metadata, checks outer-run
   ancestry, acquires a budget lease, hashes the prompt for lifecycle evidence,
   applies the optional prompt-size ceiling, resolves Codex account identity
   evidence for Codex models, and starts the call monitor.
3. `_call_llm_impl` bridges sync execution into `_acall_llm_impl`, which builds
   replay input, resolves the ordered call plan, validates requested execution
   capabilities, and chooses transport per resolved model.
4. `execution_kernel.py` applies retry within a model and fallback between
   models; each retry log line names the model and task and uses a compact
   error summary (`_retry_error_summary`). The Responses, completion, and agent adapters normalize their
   outputs into `LLMCallResult`.
5. Result finalization attaches requested/resolved identity, routing trace,
   warnings, cache accounting, and call evidence. The wrapper emits completed
   or failed lifecycle state and settles only cost it can truthfully own.

# Edit map

- Public parameter: [Public API and contracts](../concepts/public-api-and-contracts.md)
- Model chain or transport: [Model selection and routing](../concepts/model-selection-and-routing.md)
- Retry/fallback: `execution/retry.py` and `execution/execution_kernel.py`
- Evidence or cost: [Observability and budgets](../concepts/observability-and-budgets.md)

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [`call_llm`, lines 463-595](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/client.py#L463-L595)
2. [Public wrapper and envelope, lines 48-153](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_wrappers.py#L48-L153)
3. [Text sync bridge, lines 64-111, and async runtime, lines 114-623](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/text_runtime.py#L64-L623)
4. [Shared execution kernel, lines 73-356](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/execution_kernel.py#L73-L356)
5. [Retry summary, lines 118-137](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/retry.py#L118-L137)
