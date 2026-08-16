---
type: concept
title: Observability and Budgets
description: How call identity, cost, lifecycle, attempts, traces, replay, and outer-run evidence fit together.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../llm_client/execution/call_wrappers.py, ../../../../llm_client/observability, ../../../../llm_client/io_log.py]
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

1. [Budget/lifecycle envelope](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/execution/call_wrappers.py#L65-L271)
2. [`ObservedRun`, lines 219–429](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/observability/observed_runs.py#L219-L429)
3. [`get_trace_tree`, lines 254–313](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/observability/query.py#L254-L313)
