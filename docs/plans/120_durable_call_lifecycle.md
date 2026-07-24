# Plan #120: Durable Cross-Project Call Lifecycle

**Status:** In Progress  
**Profile:** production-internal; runtime-state, migration, LLM overlays

## Outcome

For every `llm_client` call, an operator can query `trace_id` or
`logical_call_id` and see a durable terminal outcome or an explicit
`interrupted_or_abandoned` state—never a silent gap.

## Boundaries and contract

| Required behavior | Owner | Additive contract | Check |
| --- | --- | --- | --- |
| Before provider I/O | public runtime envelope | `call_lifecycle_events` row: `dispatched` | provider fake sees prior durable row |
| Provider/parse/retry/timeout/terminal transitions | execution and structured-attempt boundaries | ordered typed events bound to logical call | deterministic event sequences |
| Query/recovery | observability query | `get_call_lifecycle()` returns terminal, active, or abandoned | dead-process/no-terminal fixture |
| Timeout truth | timeout policy/runtime | requested timeout, selected transport acceptance, whole-call vs provider-attempt boundary | timeout fixtures |

`logical_call_id`, trace, task, project, requested/resolved model, prompt hash,
schema hash, configured timeout, process identity, and causal parent are stored
when available. Missing values are explicit nulls; no value is invented.

## Compatibility and migration

- Preserve `llm_calls`, `structured_attempt_events`, and `foundation_events`.
- Add `call_lifecycle_events` plus indexes only; old databases migrate
  additively and remain queryable.
- Continue emitting legacy foundation lifecycle events during transition; the
  new query reads the new table first and labels legacy-only evidence as such.

## Thin slices

1. Typed event schema, additive storage, dispatch-before-I/O, and query that
   classifies stale/dead-process nonterminal calls as `interrupted_or_abandoned`.
2. Route text, structured, async, stream, retry, parse, and timeout boundaries
   through the shared emitter; prove ordered fixtures for complete/error/parse/
   retry/timeout/interruption.
3. Run one bounded real structured call against the shared database and retain
   the exact `trace_id`/`logical_call_id`; no model-quality claim follows.

## Non-claims

- A process cannot emit an event after forceful external termination; recovery
  infers only `interrupted_or_abandoned`, never a provider outcome.
- Provider timeout, client attempt safety ceiling, and whole-call deadline stay
  distinct; no timeout is shortened to manufacture evidence.
- No project-specific manifest, LLM call, or provider-dashboard dependency.

## Required evidence

- deterministic complete, provider-error, parse-error, retry, timeout, and
  dispatch-without-terminal fixtures;
- migration and ordering tests;
- one real structured call after deterministic coverage is green.

## Required Tests

- `tests/test_call_lifecycle_ledger.py`
- `tests/test_client_lifecycle.py`
- `tests/test_structured_attempts.py`
- `tests/test_structured_runtime.py`
- `tests/test_io_log.py`

## Live evidence

On 2026-07-24, a bounded DeepSeek V4 Flash structured call used trace
`llm_client.lifecycle_probe.20260724.terminal` and logical call
`cbf9dcb9f4d845e9b6d597206cb5b01f`. The shared database recorded ordered
`provider_dispatched`, `provider_response`, `parse_or_validation_succeeded`,
and `completed` events. The result was `{"status": "ok"}` at $0.0000028.
This proves this exact structured route and terminal binding; it does not prove
timeout, cancellation, or every text/stream path.

## Current implementation evidence (2026-07-24)

- `call_lifecycle_events` is an additive SQLite ledger, written before the
  legacy Foundation event so persistence failure is visible at the integrity
  seam.
- `get_call_lifecycle(logical_call_id=...|trace_id=...)` returns its latest
  event and elapsed time. It reports `active` only with evidence that the
  recorded same-host process is still alive; otherwise nonterminal evidence is
  `interrupted_or_abandoned`.
- Structured attempt events project provider dispatch/response, parse success
  or failure, retry decision, and timeout/provider error into the same ledger.
  The structured runtime binds its terminal event to the attempt logical call.
- Deterministic tests cover completion, provider error, parse error, retry,
  timeout, caller cancellation, and a dispatch row with no terminal event.

Remaining work before this can be called complete: make prompt/schema/causal
and transport-timeout fields first-class ledger columns for every public path;
unify outer public-call and inner structured logical identities; and execute a
real process-interruption recovery probe. These are intentionally not claimed
by the live structured success probe.
