---
type: workflow
title: Structured-Call Lifecycle
description: End-to-end path from a Pydantic response model to validated output and attempt-level evidence.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../llm_client/core/client.py, ../../../../llm_client/execution/structured_runtime.py, ../../../../llm_client/observability/structured_attempts.py]
confidence: high
---

# Flow

```text
call_llm_structured(response_model)
  -> resolve timeout + public task/trace/budget envelope
  -> structured runtime resolves model chain and schema policy
  -> choose native JSON Schema | Responses | Instructor fallback
  -> provider attempt and exact raw-content custody
  -> Pydantic validation
  -> record attempt/recovery/diagnostic evidence
  -> return (validated model, LLMCallResult)
  -> terminal lifecycle and budget settlement
```

# Important distinctions

The response model plays two roles: it supplies the JSON Schema sent to a
capable provider and validates the returned value locally. A successful
transport is not automatically a valid structured result, and a valid model
instance does not replace the original payload when evidence custody requires
provider bytes.

The runtime can use provider-native schema support, the Responses API, or an
Instructor adapter. `StructuredOutputPolicy` controls whether fallback across
those routes is permitted; strict native-schema execution fails visibly if the
selected route cannot satisfy the contract. A separate logical timeout can
bound the whole retry/fallback chain. Attempt events preserve validation
issues, failure classes, and recovery decisions, while content policy governs
whether durable stores may retain prompt/response material.

# Edit map

- Public behavior and parameters: `core/client.py`.
- Route selection, parsing, validation, raw custody orchestration:
  `execution/structured_runtime.py`.
- Attempt ledger: `observability/structured_attempts.py`.
- Exact raw payload store: `observability/raw_artifacts.py`.
- Shared retry/fallback timing: `execution/execution_kernel.py`.

Read [Structured output](../concepts/structured-output.md) for the conceptual
contract and [Observability and budgets](../concepts/observability-and-budgets.md)
for the surrounding evidence lifecycle.

# Citations

1. [`call_llm_structured`, lines 596–718](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/core/client.py#L596-L718)
2. [Structured runtime implementation](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/execution/structured_runtime.py#L974-L2266)
3. [Structured-attempt evidence contracts](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/observability/structured_attempts.py)
