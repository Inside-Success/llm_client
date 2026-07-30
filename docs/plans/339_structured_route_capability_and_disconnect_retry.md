# Plan #339: Structured Route Capability and Disconnect Retry

**Status:** 🚧 In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Process Tracing Plan 020 terminal repair replay

---

## Outcome

One governed structured call can distinguish model-level typed-output
eligibility from route-level native-JSON-Schema execution, and can retry a
transient remote disconnect without retrying permanent quota or route
compatibility failures. Each actual provider dispatch remains visible under a
distinct attempt ordinal.

The actor is a maintained downstream executable such as Process Tracing. The
inspectable target is one unchanged Process Tracing Terra-medium terminal
repair replay whose shared-client lifecycle either completes or records every
provider dispatch and terminal disposition truthfully.

## Gap

**Current:** `ModelInfo.structured_output` simultaneously controls task-model
eligibility and `_model_supports_native_schema()`. Fresh Process Tracing probes
on 2026-07-29 found that OpenRouter Luna-medium and Sol-medium had endpoints but
none accepted the requested native structured parameters, despite retained
successful but schema-specific route evidence. Separately, OpenRouter wrapped
`Server disconnected without sending a response` in a generic `APIError`; the
retry classifier did not recognize that transport phrase, so
`num_retries=2` produced only attempt ordinal `0` and a terminal
`retry_exhausted` event.

**Target:** Preserve Luna and Sol as explicit structured-work candidates while
routing their current OpenRouter identities through the Instructor path unless
fresh route-specific native-schema evidence promotes them. Classify the exact
remote-disconnect envelope as transient. Preserve permanent capability, quota,
authentication, and policy failures as single-dispatch terminals.

**Why:** A model capability declaration is not evidence that every route and
schema combination accepts native JSON Schema. A configured retry count is not
real resilience unless transient failures cause another observable dispatch.

## Scope

### In scope

- Separate overall structured-output eligibility from native-schema transport
  preference in the typed registry contract.
- Conservatively mark the current OpenRouter Luna and Sol routes as not
  generally native-schema-capable while retaining their structured eligibility
  and bounded historical certifications.
- Recognize the observed remote-disconnect transport envelope as retryable.
- Prove retry dispatches and durable attempt ordinals through the real
  structured runtime, then run one non-mocked downstream replay.
- Update model-selection and route-evidence documentation without claiming
  universal model incapability.

### Non-goals

- Compare Luna, Sol, Terra, or DeepSeek semantic quality.
- Build a live endpoint-capability database or schema compatibility predictor.
- Retry OpenRouter `no compatible endpoints`, quota exhaustion,
  authentication, content-policy, or local validation terminal failures.
- Change Process Tracing evidence, hypotheses, prompts, budgets, or frozen
  terminal inputs.
- Make Luna or Sol an automatic Process Tracing fallback.

## References Reviewed

- `CLAUDE.md` - runtime-substrate, structured-output, observability, and
  fail-loud rules.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` - route
  capability belongs to current provider evidence, not a fabricated endpoint
  inventory.
- `docs/plans/110_provider-capabilities-opus-ban.md` - provider capability and
  normalized-parameter ownership.
- `docs/plans/117_explicit_reasoning_policy.md` - governed reasoning contract.
- `docs/plans/336_typed_openrouter_route_policy.md` - no-compatible-route is a
  non-retryable capability failure.
- `docs/plans/337_current-model-selection-evidence-and-gpt-5-5-retirement.md`
  - current Luna/Sol registry claims and bounded certification language.
- `docs/runs/2026-07-21_openrouter_gpt56_planner_schema_compatibility.md` -
  retained Luna planner-schema success and its explicit scope limit.
- `docs/runs/2026-07-25_openrouter_gpt56_sol_authoring_schema_certification.md`
  - retained Sol authoring-schema success and invalidation inputs.
- `llm_client/core/models.py` - registry schema, selectors, and current
  `supports_structured_output()` contract.
- `llm_client/execution/structured_runtime.py` - native-schema versus
  Instructor dispatch and global structured-attempt ordinals.
- `llm_client/execution/retry.py` and
  `llm_client/execution/execution_kernel.py` - retry classification and
  dispatch loop.
- Process Tracing traces
  `process-tracing.luna-medium-capability-probe.20260729T222353Z`,
  `process-tracing.sol-medium-capability-probe.20260730T000519Z`, and
  `plan020-terra-medium-repair-enabled-20260729T235130Z` - fresh route and
  retry evidence.

## Boundaries and Contracts

```text
task selector
  | requires structured output
  v
ModelInfo.structured_output --------------------> model remains eligible
  |
  `-- ModelInfo.native_structured_output
         | true  -> native json_schema transport
         | false -> Instructor structured transport
         ` null  -> legacy-compatible fallback to structured_output

provider exception
  -> retry classifier
       | transient disconnect -> retry decision -> next provider dispatch
       | permanent failure    -> exhausted decision -> raise
       ` every dispatch       -> unique structured attempt ordinal
```

### Registry schema

Add `native_structured_output: bool | None = None` to `ModelInfo` and packaged
model records where route evidence requires an explicit distinction.

| Field | Meaning | Selector effect | Runtime effect |
| --- | --- | --- | --- |
| `structured_output` | Model is eligible for maintained typed-output work through some governed client path | Required by structured task profiles | Does not alone force native transport after this plan |
| `native_structured_output` | Curated current route may receive provider-native `json_schema` for the general shared-client contract | None | `true` selects native; `false` selects Instructor; `null` preserves legacy behavior by falling back to `structured_output` |

Compatibility is additive: existing external registry files that omit the new
field continue to behave as before. Luna and Sol keep
`structured_output=true`, receive `native_structured_output=false`, and lose
the misleading `structured-route-certified` tag in favor of bounded-evidence
wording. Terra remains native for the accepted Process Tracing route.

### Retry contract

The observed text `server disconnected without sending a response` is a
transient transport signature. It may consume only the caller's existing
bounded retry budget. The implementation must not make generic `APIError`
retryable and must keep these signs terminal:

- HTTP 404/no compatible endpoints;
- `insufficient_quota` or other permanent quota exhaustion;
- authentication/permission failures;
- local configuration, capability, finalization, and policy failures.

For `max_retries=N`, actual dispatch ordinals are `0..N` at most. A retry
decision is persisted before the next dispatch; terminal exhaustion is
persisted once for the final attempted ordinal.

## Files Affected

- `llm_client/core/models.py` (modify)
- `llm_client/data/default_model_registry.json` (modify)
- `llm_client/execution/structured_runtime.py` (modify)
- `llm_client/execution/retry.py` (modify)
- `tests/test_models.py` (modify)
- `tests/test_structured_capability_registry.py` (modify)
- `tests/test_structured_attempts.py` (modify)
- `tests/test_structured_timeout_deadline.py` (modify)
- `docs/guides/model-selection.md` (modify)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate only if
  public generated output changes)
- `docs/plans/337_current-model-selection-evidence-and-gpt-5-5-retirement.md`
  (add superseding capability clarification)
- `docs/plans/339_structured_route_capability_and_disconnect_retry.md`
  (update status/evidence)
- `docs/plans/CLAUDE.md` (modify)

## Plan

Implement and verify the following risk-ordered thin slices without changing
their frozen boundaries.

## Thin Slices

### Slice 1: Capability separation (`fully_specifiable_now`)

Add the optional native-transport field, route runtime dispatch through it,
and set explicit Luna/Sol conservative values. Positive fixtures prove Luna
and Sol remain structured-task candidates but select Instructor. A null-field
fixture proves old custom registries preserve behavior. Malformed non-boolean
values fail Pydantic/registry validation.

### Slice 2: Disconnect retry (`fully_specifiable_now`)

Add the exact remote-disconnect signature to transient classification. A
structured-runtime fixture raises that envelope once, succeeds on the next
dispatch, and proves lifecycle ordinals `0` and `1`. Negative fixtures prove
quota and no-compatible-route errors remain one-dispatch terminals.

### Slice 3: Live downstream acceptance (`conditional`)

Publish the accepted shared-client revision, pin Process Tracing to it, and run
the unchanged Terra-medium repair-enabled replay. If the provider disconnects,
the trace must show bounded redispatch. If no transient failure occurs, a
separate inexpensive real route probe may exercise retry only when a safe
provider-level fault injection is available; do not fabricate a successful
downstream retry claim from deterministic tests alone.

## Required Tests

| Test file | Required proof |
| --- | --- |
| `tests/test_structured_capability_registry.py` | Overall and native capability fields are distinct; null preserves legacy registry behavior; Luna/Sol are conservative native negatives. |
| `tests/test_models.py` | Luna/Sol remain eligible/selectable for structured work; existing tiers do not silently change. |
| `tests/test_structured_attempts.py` | Exact remote-disconnect envelope redispatches and produces unique durable ordinals; terminal negatives do not redispatch. |
| `tests/test_structured_timeout_deadline.py` | Transport signature is retryable while quota/no-compatible-route signs remain non-retryable. |
| `tests/test_structured_runtime.py` | Native and Instructor dispatch selection remains correct. |
| `make check` | Full repository tests, typing, lint, generated-surface, and relationship gates pass or any pre-existing baseline is documented without suppression. |

## Acceptance and Disproof

- [ ] Luna and Sol remain typed-output candidates but do not use native schema
      by default on the current OpenRouter routes.
- [ ] Terra and previously certified unaffected routes preserve native-schema
      execution.
- [ ] The exact observed remote disconnect is classified transient without
      making all `APIError` instances retryable.
- [ ] A structured call with retries produces a second real invocation and
      unique attempt ordinals after the controlled disconnect fixture.
- [ ] Quota and no-compatible-route fixtures terminate after ordinal `0`.
- [ ] Focused tests and full repository gates pass.
- [ ] One non-mocked Process Tracing replay uses the published revision and
      preserves exact frozen input hashes.

The plan is disproved if Luna/Sol become ineligible for all structured work,
if a permanent failure redispatches, if retry warnings appear without a second
invocation, if attempt ordinals are reused, or if the downstream replay uses a
different corpus, prompt, mechanism input, or terminal constraint.

## Failure, Recovery, and Rollback

- Registry parse or compatibility failure: do not publish; revert the additive
  field slice on the plan branch.
- Unexpected selector change: restore the prior selector output before any
  live probe; no automatic model substitution is permitted.
- Retry regression: retain the current fail-loud terminal behavior rather than
  broadening exception classes.
- Live provider failure: preserve the full lifecycle and intermediate
  Process Tracing artifacts, report the exact provider/route evidence, and do
  not silently switch models or alter frozen inputs.
- Rollback is a normal revert of the shared-client merge plus restoration of
  the prior Process Tracing runtime pin; no data migration is involved.

## Completion Evidence

Record the merge revision, focused/full test commands and counts, generated
surface checks, real route capability receipt, Process Tracing runtime manifest
digest, frozen input digests, downstream trace/run IDs, actual provider attempt
ordinals, cost, and final artifact disposition. Completion supports only the
bounded capability and retry claims above, not semantic model superiority or
universal route availability.

### Implementation evidence (2026-07-30)

- Capability, retry-classification, and real structured-runtime ledger tests:
  `40 passed`.
- Plan test harness across all five declared test modules: `112 passed`.
- Broad suite excluding only the unavailable optional LangGraph module:
  `1966 passed, 47 skipped, 12 deselected, 2 failed`. The same two failures
  reproduce on unchanged `main`: the provider-limit subprocess invokes
  `/usr/bin/python` without Pydantic, and the stale public-surface fixture
  expects 138 exports while canonical `main` exposes 145.
- Ruff passes on every changed Python file. The aggregate gate still reports
  the documented 299-error repository baseline. MyPy reaches one unchanged
  `llm_client/parsing_utils.py` `no-any-return` finding while checking the
  changed dependency graph.
- Markdown links, relationship validation, registry JSON parsing, generated
  API reference generation, plan-status consistency, and `git diff --check`
  pass. AGENTS rendering remains blocked by the canonical checkout's existing
  `AGENTS.md -> CLAUDE.md` symlink guard; this plan does not mutate governance
  generation.
- The controlled exact OpenRouter disconnect produced dispatch ordinals `0`
  and `1`; permanent quota and no-compatible-route controls remained terminal.
- Shared-client publication and the unchanged non-mocked Process Tracing replay
  remain required before this plan can advance beyond in progress.
