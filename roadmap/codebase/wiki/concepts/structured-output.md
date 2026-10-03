---
type: concept
title: Structured Output
description: How Pydantic response contracts are routed, validated, retained, and reported without treating parsing as proof.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/core/client.py, ../../../../llm_client/execution/structured_runtime.py, ../../../../llm_client/observability/structured_attempts.py, ../../../../llm_client/observability/raw_artifacts.py, ../../../../llm_client/core/errors.py, ../../../../llm_client/execution/timeout_policy.py]
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

# Provider-reported failure

Some providers return a successful response whose raw finish reason is
`error` (for example an upstream provider dying mid-generation), which LiteLLM
normalizes to `stop`. `_raise_on_provider_failure_finish_reason` in
`execution/structured_runtime.py` checks the preserved
`provider_specific_fields["native_finish_reason"]` (falling back to
`finish_reason`) before schema validation and raises the retryable
`LLMProviderResponseError`, so the failure is classified as a provider failure
instead of a misleading schema error. It runs on both the native-schema and the
Instructor paths, in the sync and async runtimes.

# Timeout default

When `LLM_CLIENT_TIMEOUT_POLICY` bans timeouts, the structured facades fill
`timeout=0` instead of the library default, so no spurious `TIMEOUT_DISABLED`
warning is produced. That warning now fires once per caller per process and
later repeats log at DEBUG.

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

All links pin Inside-Success/llm_client at `fe581ed`.

1. [`call_llm_structured`, lines 606-736](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/client.py#L606-L736) and [`acall_llm_structured`, lines 945-1074](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/client.py#L945-L1074)
2. [Structured runtime implementations, lines 1033 and 2347](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/structured_runtime.py#L1033-L1100)
3. [Provider-failure check, lines 912-941](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/structured_runtime.py#L912-L941)
4. [`LLMProviderResponseError`, lines 79-99](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/core/errors.py#L79-L99)
5. [Policy models, lines 75-100](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_contracts.py#L75-L100)
6. [Timeout policy, lines 40-154](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/timeout_policy.py#L40-L154)
7. [Structured-attempt contracts](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/observability/structured_attempts.py); [raw artifact custody](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/observability/raw_artifacts.py)
