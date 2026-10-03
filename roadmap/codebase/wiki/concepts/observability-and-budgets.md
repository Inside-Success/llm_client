---
type: concept
title: Observability and Budgets
description: How call identity, cost, lifecycle, attempts, traces, replay, and outer-run evidence fit together.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/execution/call_wrappers.py, ../../../../llm_client/observability, ../../../../llm_client/io_log.py, ../../../../llm_client/execution/call_lifecycle.py, ../../../../llm_client/execution/codex_identity.py, ../../../../llm_client/langfuse_callbacks.py, ../../../../llm_client/utils/litellm_log_filters.py]
confidence: high
---

# Evidence layers

Observability is not one log record. The public wrapper establishes a call
lifecycle and budget lease before transport begins, emits started/heartbeat/
terminal lifecycle evidence, and settles or releases the lease according to
known cost custody. Runtime paths record call results, routing traces, attempts,
errors, costs, cache status, and optional content according to policy.

The `observability/` package adds query and comparison surfaces, exact call
receipts, structured-attempt ledgers, raw artifact custody, selected-attempt
receipts, replay snapshots, tool calls, interventions, experiments, and
`ObservedRun`—an outer lifecycle for applications that may make zero or more
LLM calls. Trace relationships are joined through trace IDs; they should not be
inferred from timestamps.

# Codex account evidence on lifecycle events

For Codex calls the wrapper passes `codex_auth_binding` (`explicit` or
`ambient`) and `codex_account_id_sha256` (a digest, or null) from
`execution/codex_identity.py` into every lifecycle event it emits;
`_emit_llm_call_lifecycle_event` in `execution/call_lifecycle.py` records both
fields. Raw account ids and paths are never stored.

# External callbacks (Langfuse)

`langfuse_callbacks.py` registers a LiteLLM callback when `LITELLM_CALLBACKS`
contains `langfuse_otel` or the legacy `langfuse` (the OTEL name is preferred
when both appear). Export content is governed by
`LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT`: the default `metadata_only` sets
LiteLLM's global `turn_off_message_logging`, dropping prompts and responses
while keeping metadata, usage, and cost; `full` must be set explicitly; any
other value raises. `LangfuseCallbackConfig` reports `enabled`, `host`,
`callback`, and `content_policy`. This is separate from the per-call
`ObservabilityContentPolicy` that governs durable local stores.

# LiteLLM log-noise filter

`utils/litellm_log_filters.py` (new since `4f7ecfa`) installs a filter on the
`LiteLLM` logger at import of `core/client.py`. It drops a record only when it
comes from `logging_worker`, starts with `LoggingWorker error`, and carries a
`CancelledError` or `TimeoutError`; every other record passes. Its docstring
records that the upstream behavior was still unfixed as of 2026-07-14.

# Budget boundary

`max_budget` is part of every public call contract. Budget scopes may be
sequential or use reservations for concurrent children. The wrapper acquires a
scope before dispatch and settles successful cost afterward. A failed call is
settled only when the exception establishes complete attempt-cost coverage;
otherwise custody is released instead of inventing a total.

Use [Text-call lifecycle](../workflows/text-call-lifecycle.md) to see where these
events surround execution and [Structured output](structured-output.md) for
attempt-specific evidence.

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [Budget/lifecycle envelope, lines 48-445](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_wrappers.py#L48-L445)
2. [Settle or release on failure, lines 180-188](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_wrappers.py#L180-L188)
3. [`ObservedRun`, lines 219-429](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/observability/observed_runs.py#L219-L429)
4. [`get_trace_tree`, lines 282-341](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/observability/query.py#L282-L341)
5. [Lifecycle event fields, lines 201-243](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/call_lifecycle.py#L201-L243)
6. [Langfuse callbacks, lines 1-217](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/langfuse_callbacks.py#L1-L217)
7. [LiteLLM noise filter, lines 1-86](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/utils/litellm_log_filters.py#L1-L86)
