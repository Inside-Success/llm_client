# ADR 0010: Cross-Project Runtime and Observability Substrate

Status: Accepted
Date: 2026-03-17
Last verified: 2026-08-20 (prompt inspection CLI surface)
Verification context: The substrate gains a read-only `prompt-show` CLI over
already-persisted calls, alongside `prompt-drift`. Both query the shared
observability store and neither adds a sink, a persisted field, a route, or a
provider interaction, so the execution and packaging guarantees this ADR makes
are unchanged and the addition is confined to the public surface it already
owns. The earlier verification still holds: the shared experiment substrate
serializes canonical run-start insertion before emitting JSONL evidence,
preventing duplicate run_id starts from appearing as two attempts.

Plan 94 adds shared authenticated OpenRouter generation evidence, an immutable
exact route-certification registry, and a provider-free query CLI. Semantic
acceptance and project-specific promotion remain above this substrate.

## Context

The intended direction for the project is that any application, coding agent, or
research workflow can point at `llm_client` for LLM and embedding work and get
standardized execution, packaging, observability, and experiment recording by
default.

At the same time, adjacent repos such as `prompt_eval` already provide
higher-level capabilities like prompt comparison, evaluators, and optimization.
That created recurring confusion about which package owns:

1. the shared execution substrate,
2. the shared observability and experiment store,
3. prompt-specific evaluation semantics,
4. workflow orchestration.

We also want to avoid recreating commodity routing and workflow machinery that
existing libraries already solve well.

## Decision

1. `llm_client` is the mandatory cross-project substrate for LLM and embedding
   execution.
2. `llm_client` owns the generic runtime surfaces that many projects share:
   - provider and SDK dispatch,
   - structured output,
   - tool calling and agent runtime integration,
   - embeddings,
   - prompt rendering,
   - cost, latency, and trace capture,
   - shared run and event persistence.
3. `llm_client` owns the authoritative shared observability backend for
   cross-project work. JSONL and SQLite are the current sinks; the storage
   backend may evolve later without changing this ownership boundary.
4. The shared experiment envelope belongs to `llm_client`, including fields such
   as `project`, `dataset`, `condition_id`, `scenario_id`, `phase`, `seed`,
   `replicate`, `metrics_schema`, `config`, `provenance`, and per-item
   `metrics`/`extra`.
5. Higher-level packages such as `prompt_eval` consume this substrate rather
   than creating separate primary execution or observability stacks.
6. Commodity routing and normalization should be wrapped instead of recreated.
   Current preference:
   - use LiteLLM for provider normalization and routing where practical,
   - use LangGraph or an equivalent workflow runtime if durable orchestration
     requirements outgrow the simple local DAG layer.
7. Workflow orchestration is above the core client boundary. `task_graph` may
   remain as a simple orchestrator, but `llm_client` should not turn into a
   bespoke general-purpose workflow engine.
8. Cross-project callers that require tool execution to be auditable use the
   shared strict tool-call API rather than implementing project-local sinks.
9. LLM-capable application entry points use the shared `ObservedRun` contract
   when pre-client validation, policy, or workflow can fail. The application
   starts outer-run custody before fallible work, derives public-call trace IDs
   from the root, and records one controlled terminal state. Public call
   wrappers reject traces outside the active run lineage before dispatch. This
   is generic run persistence, not workflow orchestration; applications retain
   stage and success semantics. Migrated executables enable
   `LLM_CLIENT_REQUIRE_OBSERVED_RUN=1`; the opt-in remains a compatibility
   bridge until consumer entry points are audited.

## Consequences

Positive:
1. A single place to standardize execution, cost tracking, and run metadata
   across projects.
2. Cleaner separation between generic runtime infrastructure and prompt-specific
   evaluation logic.
3. Lower risk of duplicating provider routing, retry, and observability code in
   every project.
4. Clearer strategy for reusing existing libraries instead of rebuilding them.

Negative:
1. `llm_client` remains a broad dependency and needs tighter module boundaries.
2. Some current behavior is transitional, especially where other packages still
   keep their own local result stores.
3. Future contributors must distinguish shared substrate features from
   higher-level product features instead of adding everything into one layer.

## Testing Contract

1. Core execution tests must continue to prove that shared runtime surfaces work
   across multiple task types, not just prompt-eval use cases.
2. Observability tests must continue to prove that run/event storage remains a
   shared facility rather than a prompt-specific one.
3. Integration work in higher-level packages should verify that they can depend
   on `llm_client` without recreating primary execution or analytics backends.
4. Strict cross-project tool traces must prove sink failures propagate and the
   persisted event remains joinable to its parent trace.
5. Cross-project structured traces must prove every provider attempt begins at
   `started`, preserves pre-response failures, and records the retry kernel's
   actual disposition with logical-call-global ordinals.
6. Downstream observed-run adoption must include pre-call failure, linked-call
   success/failure, and cancellation controls plus one non-mocked root-to-child
   lifecycle receipt before advertising complete integration.

Last verified: 2026-07-28 (Plan 338 observed application-run lifecycle).

The shared runtime now distinguishes provider recovery from local finalization:
once native structured output validates, hook/cache/log failures fail loud
without repeating generation or switching models.

Plan 101 consumers pin the logical call identity returned by the same runtime
result; trace-only lookup is diagnostic.

Plan 354 reasserts public-wrapper ownership of the structured call's sole
terminal lifecycle. Private runtimes still persist one terminal call row and
structured-attempt events under the same logical call ID; composed sync/async
controls prove the joined boundary.

Plan 356 makes Instructor a first-class structured-attempt path without moving
evaluation semantics into this substrate. The shared retry kernel owns retry
count and disposition, and downstream evaluations may require the resulting
attempt receipt before treating a model result as execution evidence.
