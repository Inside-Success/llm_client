---
type: concept
title: Structured Output
description: How Pydantic response contracts are routed, validated, retained, and reported without treating parsing as proof.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../llm_client/core/client.py, ../../../../llm_client/execution/structured_runtime.py, ../../../../llm_client/observability/structured_attempts.py, ../../../../llm_client/observability/raw_artifacts.py]
confidence: high
---

# Contract

`call_llm_structured` and `acall_llm_structured` accept a Pydantic model class
and return both the validated model instance and `LLMCallResult`. The public
facade resolves timeout policy, prepares the same task/trace/budget envelope as
text calls, and delegates to the structured runtime.

The structured runtime selects among provider-native JSON Schema, the Responses
route, and an Instructor-based fallback according to model capability and the
caller’s `StructuredOutputPolicy`. Native strict mode fails rather than quietly
changing execution paths. Validation failures, retries, recovery decisions,
attempt diagnostics, and exact raw structured payload custody have separate
observability contracts; a parsed Pydantic object is not substituted for the
provider bytes when evidence requires the original content.

# Design consequences

- Schema descriptions are part of the provider contract, not decorative docs.
- Logical timeout can bound the complete retry/fallback chain separately from
  per-attempt timeout.
- Content policy can retain metadata while deliberately omitting prompt or
  response content.
- Route certification is downstream evidence and is not inferred merely from
  a requested model name.

Follow the [structured-call lifecycle](../workflows/structured-call-lifecycle.md)
for the complete flow and [Observability and budgets](observability-and-budgets.md)
for the evidence boundaries.

# Citations

1. [`call_llm_structured`, lines 596–718](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/core/client.py#L596-L718)
2. [Structured runtime module and route responsibilities](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/execution/structured_runtime.py#L1-L80)
3. [Exact raw structured-artifact custody](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/observability/raw_artifacts.py)
