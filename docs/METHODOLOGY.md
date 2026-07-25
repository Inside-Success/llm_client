# LLM Client Methodology

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Goal

`llm_client` gives projects a single governed runtime for model and tool calls.
The goal is not to wrap every possible workflow. The goal is to make every LLM
operation observable, budgeted, typed where possible, and traceable enough that
downstream systems can debug their own behavior.

The target loop is:

```text
task intent -> model selection -> call execution -> structured result -> observability -> downstream decision
```

## Design Method

The repo uses a runtime-substrate pattern:

1. Projects call a small set of sync/async runtime functions.
2. Calls carry task, trace, and budget metadata.
3. Model routing is task-based where possible instead of hardcoded locally.
4. Structured output is treated as a schema contract, not prompt decoration.
5. Runtime results include cost, usage, route, error, and validation context.
6. Observability is written to durable JSONL and SQLite surfaces.
7. Prompt evaluation and application semantics stay in adjacent repos.

This keeps the shared layer focused on execution and diagnostics while applied
projects own what the call is supposed to mean.

## Borrow-Vs-Build

Borrowed:

- LiteLLM for provider normalization and transport where practical;
- provider APIs and SDKs for direct model execution;
- Pydantic and JSON schema conventions for structured output;
- SQLite and JSONL as simple durable observability sinks.

Built locally:

- required call metadata and budget enforcement;
- task-based model registry and routing policy;
- sync/async runtime surfaces;
- structured-output parsing and validation wrappers;
- cost, token, latency, error, and trace observability;
- tool-call logging surface;
- replay and divergence diagnosis surfaces;
- project-facing CLI and Make targets.

## Modality Split

Deductive / plan-first surfaces:

- public runtime function contracts;
- required metadata semantics;
- observability record shape;
- structured-output schema handling;
- model registry data and config precedence;
- ownership boundary with `prompt_eval` and `project-meta`.

Exploratory / ladder surfaces:

- which model is best for a specific downstream task;
- when a provider route should be demoted or retried;
- what latency/cost threshold is acceptable for an applied workflow;
- which traces are worth turning into portfolio evidence;
- whether future workflow requirements need a separate durable runtime layer.

Exploratory surfaces need observed call data, not speculation.

## ADR Map

- [0007-observability-contract-boundary.md](adr/0007-observability-contract-boundary.md)
  defines the observability contract boundary.
- [0010-cross-project-runtime-substrate.md](adr/0010-cross-project-runtime-substrate.md)
  defines the cross-project runtime substrate.
- [0015-portfolio-runtime-substrate-scope.md](adr/0015-portfolio-runtime-substrate-scope.md)
  records the portfolio scope decision: support applied traces, do not lead as
  a standalone analyst product.

## Main Failure Modes

| Failure mode | Why it matters | Control |
|---|---|---|
| Leading with infrastructure breadth | Reviewers may not see analytic value. | Attach to applied decisions and traces. |
| Treating observability as proof | Trace data explains execution, not claim truth. | Downstream projects own analytic validation. |
| Regrowing prompt evaluation | Blurs boundary with `prompt_eval`. | Capability decomposition and ADR controls. |
| Becoming a workflow engine | Bloats the runtime substrate. | Keep durable orchestration above this layer. |
| Estimating instead of querying costs | Produces unreliable governance claims. | Query the observability database. |
