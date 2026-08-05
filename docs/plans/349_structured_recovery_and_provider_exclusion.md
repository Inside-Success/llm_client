# Plan #349: Structured Recovery and Provider Exclusion

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Process Tracing default-route correction

---

## Outcome

A malformed provider response receives one explicit JSON-repair instruction
inside the caller's existing retry bound, and maintained callers can exclude a
known-bad OpenRouter provider through the typed route policy. Process Tracing
then pins the accepted client revision, uses Luna as its governed default, and
excludes Morph whenever DeepSeek is selected explicitly.

The visible result is a new Process Tracing run confirmation that identifies
Luna as the default route while preserving DeepSeek as an explicit governed
alternative. No paid model call is required to accept the deterministic slice.

## Gap

**Current:** `OpenRouterRoutePolicyV1` can allowlist providers but cannot express
OpenRouter's supported `ignore` control. Native-schema validation failures add
a repair instruction, while completely malformed JSON retries the unchanged
prompt. Process Tracing pins client revision `c608df6`, silently defaults to
DeepSeek V4 Flash, and does not pass a typed provider route policy.

**Target:** Add replay-safe provider exclusions, make malformed-JSON retry
corrective, and consume both through the governed Process Tracing boundary.

**Why:** Retained Process Tracing evidence includes Morph engine shutdowns and
DeepSeek malformed structured output. The shared client already owns routing,
retry, replay, and structured-output recovery, so applications should not
duplicate raw provider dictionaries or retry prompts.

## Boundaries

### In scope

- Add `ignored_providers` to `OpenRouterRoutePolicyV1` and compile it to
  OpenRouter `provider.ignore`.
- Reject duplicate/blank ignored providers and overlap between allowed and
  ignored provider sets before dispatch.
- Preserve policy identity through snapshot and replay.
- Add a concise parse-repair message after a malformed JSON response.
- Keep all retries within the caller's existing retry, deadline, and budget
  controls.
- Pin Process Tracing to the accepted shared-client revision, default its
  governed analysis route to OpenRouter Luna, and apply a typed Morph exclusion
  to explicit DeepSeek calls.

### Non-goals

- Dynamic endpoint inventories or automatic health databases.
- Silent model fallback or model-quality claims.
- Retrying semantic rejections after a response satisfies its Pydantic schema.
- Changing Process Tracing prompts, methodology, aggregate budget semantics,
  or accepted reports.
- A paid live run, package release, or deployment.

## Adopted Contract

Design revision `plan-349-v1` adopts these rules:

1. Provider exclusions are caller-declared routing intent, not a global mutable
   provider blacklist.
2. `allowed_providers` and `ignored_providers` may not overlap case-insensitively.
3. Malformed JSON receives a bounded generic repair instruction; validation
   failures retain their field-specific repair path.
4. A schema-valid but semantically bad response remains terminal to the shared
   client. Domain audits remain the consumer's responsibility.
5. Process Tracing uses the user-approved Luna/Medium route by default. An
   explicit DeepSeek selection remains allowed and carries the Morph exclusion.
6. Existing callers that omit the new field remain byte-for-behavior compatible.

OpenRouter's current provider-routing documentation explicitly supports
`ignore`; the shared client continues to borrow that transport control rather
than maintaining endpoint availability data.

## Files Affected

### Shared client

- `llm_client/execution/call_contracts.py`
- `llm_client/execution/structured_runtime.py`
- `llm_client/utils/openrouter.py`
- `tests/test_openrouter_route_policy.py`
- `tests/test_structured_runtime.py`
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- generated API reference surfaces when the public model changes

### Process Tracing integration

- `config/llm_client_runtime.json`
- `pt/llm.py`
- `pt/templates/workbench.html`
- focused LLM and workbench tests
- current status after deterministic integration evidence

## Work Graph

The machine-consumed graph is
[`supporting/349_work_graph.json`](supporting/349_work_graph.json). WU-349-01
owns the shared contract. WU-349-02 depends on its accepted revision and owns
the Process Tracing integration.

## Required Tests

| Surface | Required proof |
| --- | --- |
| Typed route policy | Ignore compiles exactly, normalizes names, rejects blank/duplicate/overlapping entries, and round-trips through replay. |
| Structured runtime | A malformed first response receives the repair message and the second response validates; zero retries still fails loud. |
| Compatibility | Existing policies without exclusions compile unchanged. |
| Process Tracing | Luna is the persisted default, Medium remains selected, explicit DeepSeek calls receive the Morph exclusion, and unsupported models fail before dispatch. |
| Integration | Process Tracing imports the exact accepted shared-client revision and focused deterministic gates pass. |

## Acceptance and Disproof

- [ ] The shared public contract and generated docs include provider exclusions.
- [ ] The exact malformed-JSON retry fixture observes a corrective message.
- [ ] No retry, timeout, budget, or semantic-acceptance bound is broadened.
- [ ] Process Tracing defaults to Luna/Medium and no longer presents DeepSeek as
      its silent default.
- [ ] Explicit DeepSeek calls compile `provider.ignore=["morph"]` through the
      typed client policy.
- [ ] Focused shared-client and Process Tracing tests pass.

The design is disproved if exclusions require a raw provider dictionary, if a
malformed response can trigger an extra dispatch beyond the configured retry
count, if semantic failures become generic client retries, or if Process
Tracing silently switches models after dispatch.

## Failure and Recovery

Both repositories use reversible feature branches. Shared-client failure stops
before the consumer pin changes. Consumer failure preserves the accepted shared
revision and restores the prior runtime pin/default in one revert. No persisted
run or accepted report is mutated.

