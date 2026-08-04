# Observed Application Runs

`ObservedRun` gives an LLM-capable executable durable outer-run custody. It is
not a workflow engine and does not replace call-level lifecycle events.

## Required placement

Create the context before input parsing, target resolution, model-policy checks,
or any other application operation that can fail:

```python
from llm_client import ObservedRun, call_llm_structured

with ObservedRun(
    project="example",
    operation="review_claims",
    executable="scripts/review_claims.py",
    run_id=run_id,
    root_trace_id=trace_id,
    runtime_revision=runtime_revision,
    config_sha256=config_sha256,
    requested_model=model,
    reasoning_effort=reasoning_effort,
    max_budget=max_budget,
) as run:
    run.set_phase("input_validation")
    inputs = validate_inputs(raw_inputs)

    run.set_phase("claim_review")
    parsed, result = call_llm_structured(
        model,
        build_messages(inputs),
        ReviewResult,
        task="example.review_claims",
        trace_id=run.child_trace_id("claim_review"),
        max_budget=max_budget,
        reasoning_effort=reasoning_effort,
    )
```

The constructor persists `running` before the context body begins. Clean exit
records `completed`. An exception with no descendant call lifecycle records
`failed_before_call_start`; this may be application validation or client
predispatch failure, and `error_phase` localizes it. An exception after any
descendant call begins records
`failed_after_call_start`. This status does not claim that the provider caused
the failure; it also covers later application failures.
`asyncio.CancelledError`, `KeyboardInterrupt`, and explicit
`run.cancel(reason=...)` record `cancelled`. Exceptions continue to propagate.

## Lineage and queries

Child identifiers are strict slash descendants of `root_trace_id`. Pass only
`run.child_trace_id(segment)` values to public LLM calls for the run. Public
call wrappers reject any unrelated trace while an `ObservedRun` context is
active, before budget reservation or provider dispatch. Query one record with
`get_observed_run(run_id)` or audit recent records with
`list_observed_runs(project=..., status=...)`. Existing trace queries expose
the descendant calls, attempts, usage, and cost.

Maintained executables should set `LLM_CLIENT_REQUIRE_OBSERVED_RUN=1` in their
governed runtime. In that mode, public text and structured calls fail before
budget reservation or provider dispatch when no `ObservedRun` is active. The
flag is opt-in during migration so existing library consumers are not broken
without an entry-point audit.

## Integration gate

A maintained executable is integrated only when tests prove:

1. pre-call validation failure leaves `failed_before_call_start`;
2. a public LLM call leaves a descendant lifecycle and the outer run reaches a
   truthful terminal state;
3. provider/structured failure leaves `failed_after_call_start` and still raises;
4. cancellation is terminal; and
5. one live non-mocked receipt exposes the root run, descendant call, and
   terminal state from the shared store.

Manual provenance files may remain domain artifacts, but they are not lifecycle
evidence and must not become a second primary observability store.
