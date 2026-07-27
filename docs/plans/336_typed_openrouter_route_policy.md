# Plan #336: Typed OpenRouter Route Policy and Consumer Migration

**Status:** 🚧 In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None for the shared-client slice; the Inside Success integration
unit is unavailable while its existing preprocessing worktree claim remains active
**Blocks:** Inside Success DP-03 real messy-Slack preprocessing vertical

---

## Execution Contract

This is the implementation packet for a lower-capability agent. Follow it in
order. Do not reopen the architectural decisions marked **frozen**. Stop at a
listed stop condition instead of inventing another routing mechanism.

| Field | Value |
| --- | --- |
| Request mode | write an implementation-ready plan; implementation is a later action |
| Design depth | Standard |
| Execution profile | pilot |
| Overlays | public API, LLM, runtime state, repository governance, cross-repository integration |
| Initiative ID | `llm-client-runtime-substrate` |
| Goal ID | `llm-client-openrouter-route-policy-v1` |
| Design revision | `plan-336-v1` |
| Landscape disposition | `linked` to ADR 0016 and OpenRouter's provider-routing contract |
| Shared-client baseline | personal `main` at `287d0cb2af229db4c03923ad4047d7dfe79310dd` on 2026-07-27 |
| Work graph | `docs/plans/supporting/336_work_graph.json` |

## Implementation Progress (2026-07-27)

- **Completed:** WU-336-01 shared-client typed policy boundary, deterministic
  payload compiler, whole-chain pre-dispatch conflict checks, typed
  no-compatible-route classification, public text/structured/stream entry
  points, and replay-safe policy serialization.
- **Observed:** a non-private native-JSON-Schema probe against
  `openrouter/deepseek/deepseek-v4-flash` returned a Pydantic-validated result
  under `data_collection="deny"` and `zdr=true`. Authenticated post-call
  evidence observed `Fireworks` as the selected upstream. See
  [`2026-07-27_typed_openrouter_route_policy_probe.md`](../runs/2026-07-27_typed_openrouter_route_policy_probe.md).
  No provider was allowlisted for that public probe, so it is not private-data
  authorization evidence.
- **Remaining:** complete the shared-client verification/closeout, then migrate
  the separately claimed Inside Success runner only after its worktree is
  available. The shared implementation was accepted into local canonical
  `main` at `b6906ba`; the consumer must pin that revision (or its approved
  published equivalent) rather than duplicate the raw provider dictionary.
  Do not broaden that runner's provider authorization automatically.
- **Publication authority resolved (2026-07-27):**
  `project-meta/PROJECT_GRAPH.json` now names `llm_client/main` as the
  canonical checkout and publication branch, matching the actual repository.

## Objective and Target

### Objective

Let a maintained caller express OpenRouter provider-routing requirements as one
validated `llm_client` object instead of constructing a raw `provider={...}`
dictionary. The client must compile that intent to OpenRouter's native routing
controls, preserve it in replay/trace evidence, and classify an unsatisfiable
route as a non-retryable capability failure.

### Actor and recurring job

The actor is an application developer or execution agent making a structured
or text LLM call through `llm_client`. The recurring job is:

1. choose one explicit model;
2. declare privacy, parameter, and upstream-provider routing constraints;
3. execute without duplicating OpenRouter payload logic in application code;
4. receive typed, locally validated output or one precise failure;
5. inspect a replayable record of the requested routing policy and actual
   provider evidence when that evidence is requested.

### Human-reviewable target artifact

The first accepted target is a retained, non-private route probe showing:

- requested model `openrouter/deepseek/deepseek-v4-flash`;
- a typed route policy compiled to the expected OpenRouter `provider` object;
- provider-native JSON Schema execution;
- one Pydantic-validated result;
- the route policy in the call snapshot;
- the actual upstream provider obtained through the existing authenticated
  generation-evidence reader; and
- no retry when a controlled provider response says no endpoint can satisfy
  the requested parameters and routing constraints.

The consumer target is then one Inside Success development preprocessing call
using the same shared policy surface, followed by the existing preprocessing
pipeline. Plan #336 does not redefine preprocessing quality.

### Success claim

Passing this plan supports only this claim:

> Maintained callers can delegate compatible-upstream selection for a fixed
> explicit model to OpenRouter through a typed, replayable `llm_client` policy,
> and an unsatisfiable route fails once as a capability error rather than being
> confused with model absence, semantic failure, or a retryable server outage.

### Disproof

The plan is disproved if any of the following remains true at the accepted
revision:

- a caller must construct the five-key OpenRouter `provider` dictionary for
  the covered Completions and Responses call paths;
- `provider.require_parameters` can become false or disappear when the typed
  policy is used;
- the requested route policy is missing or unreplayable in the call snapshot;
- a known OpenRouter “no compatible endpoints” response is classified as
  model-not-found or retried within the same logical call;
- the policy is silently sent to a non-OpenRouter route;
- raw `provider` kwargs and the typed policy are merged by precedence rather
  than rejected as ambiguous; or
- the real non-private probe succeeds through an upstream provider outside the
  policy's allowlist.

Passing does **not** prove that every provider is available, that OpenRouter
will never change, that a model produces good semantics, or that private Slack
processing is authorized.

## Gap

### Current

- `llm_client.core.models.supports_structured_output(model)` records a
  model-level declaration. It does not establish that an endpoint exists under
  a particular privacy/provider policy.
- `llm_client.utils.openrouter._enable_openrouter_inline_metadata()` preserves
  caller-supplied provider routing and forces `require_parameters=true` when a
  normalized parameter is forwarded, but callers still construct the remaining
  OpenRouter dictionary themselves.
- `llm_client.route_certification_runtime` can record the actual upstream only
  after a successful call. It deliberately does not select or substitute a
  provider.
- `classify_error()` currently allows a LiteLLM/OpenRouter HTTP 404 for “no
  endpoints found that can handle the requested parameters” to look like
  `LLMModelNotFoundError`, even though the model exists and the route constraints
  are unsatisfiable.
- The active Inside Success runner currently pins `provider.only` to one
  `ProviderDataAuthorizationV1.upstream_processor`, plus `data_collection=deny`,
  `zdr=true`, `allow_fallbacks=false`, and `require_parameters=true`. Its
  observed direct-DeepSeek pin has no compatible ZDR endpoint.

### Target

- A strict Pydantic `OpenRouterRoutePolicyV1` is public from `llm_client`.
- Shared call preparation is the sole compiler from that object to the
  OpenRouter `provider` payload for covered completion paths.
- Existing raw `provider` kwargs remain temporarily compatible only when the
  typed policy is absent.
- Unsatisfiable route responses become `LLMNoCompatibleRouteError`, a
  non-retryable `LLMCapabilityError` subtype.
- The policy is part of call identity, replay, and privacy-bounded diagnostics.
- Inside Success consumes the typed policy and stops constructing a raw
  provider dictionary.
- Broader migration and deletion happen only after the first consumer is
  observed working.

## Frozen Design Decisions

1. **Keep `llm_client`.** OpenRouter owns current upstream routing and transport
   capability matching. `llm_client` continues to own stable call contracts,
   local validation, policy, retry, budgets, evidence, and replay.
2. **Do not build a live endpoint registry.** Normal calls must not fetch or
   cache `/endpoints` metadata. This preserves ADR 0016's boundary and avoids a
   second stale provider-capability database. The provider response remains the
   runtime authority for route satisfiability.
3. **Keep explicit model selection.** This plan does not enable OpenRouter Auto
   Router, presets, model arrays, or account-side model selection.
4. **Provider fallback means same-model upstream fallback.** It does not change
   the requested model and does not bypass the existing model allowlist.
5. **Keep model-level structured capability separate from route readiness.** Do
   not delete `supports_structured_output()` in this plan. Correct its docs so
   it cannot be cited as proof that a policy-constrained route is available.
6. **Reject ambiguous ownership.** A call may supply either
   `openrouter_route_policy` or raw `provider` kwargs, never both.
7. **Fail before dispatch on local misuse.** A typed OpenRouter policy on a
   non-OpenRouter route is `LLMConfigurationError` with
   `error_code="openrouter_route_policy_on_non_openrouter_route"`.
8. **Do not broaden data authorization.** A provider allowlist in this object
   constrains routing; it does not authorize private data transmission. The
   consumer remains responsible for a valid authorization covering every
   listed upstream processor and source field.
9. **No automatic retry for an unsatisfiable route.** A different policy or
   changed upstream state requires a new logical call with a fresh trace.
10. **First prove one useful vertical.** Do not begin ecosystem-wide caller
    cleanup until the Inside Success development preprocessing call completes
    through this boundary.

## References Reviewed

### Repository authority and implementation

- `CLAUDE.md` — runtime-substrate identity, plan workflow, structured-output,
  trace, and fail-loud rules.
- `docs/plans/01_master-roadmap.md` — canonical program authority.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` — borrow
  OpenRouter/LiteLLM capabilities; keep local enforcement and evidence; do not
  build a second provider capability database.
- `docs/plans/99_strict_native_json_schema_execution.md` — native-schema policy
  and failure semantics.
- `docs/plans/110_provider-capabilities-opus-ban.md` — normalized parameters,
  `require_parameters`, and provider-routing ownership.
- `llm_client/core/models.py` — model-level structured capability registry.
- `llm_client/execution/call_contracts.py` — current typed call policy home.
- `llm_client/execution/completion_runtime.py` — common completion kwargs
  compiler used by sync, async, structured, tool, and streaming paths.
- `llm_client/utils/openrouter.py` — current OpenRouter policy and trace
  projection seam.
- `llm_client/core/errors.py` — public error taxonomy.
- `llm_client/observability/replay.py` — call snapshot and replay contract.
- `llm_client/openrouter_generation.py` and
  `llm_client/route_certification_runtime.py` — post-call actual-upstream
  evidence.
- `tests/test_provider_kwargs.py`, `tests/test_errors.py`,
  `tests/test_observability_replay.py`, `tests/test_structured_runtime.py`, and
  `tests/test_structured_attempts.py` — current contract coverage.

### Moving external contract, observed 2026-07-27

- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
  — `only`, `allow_fallbacks`, `require_parameters`, `data_collection`, and
  `zdr` are native provider-routing controls.
- [OpenRouter ZDR](https://openrouter.ai/docs/guides/features/zdr) — `zdr=true`
  restricts routing to endpoints under the Zero Data Retention policy.
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
  — JSON Schema is expressed through `response_format`.
- `GET https://openrouter.ai/api/v1/endpoints/zdr` was read only as planning
  evidence. Its provider availability is mutable and must not be copied into
  runtime code, tests, or a durable allowlist.

### Consumer evidence

- `inside_success/preprocessing/run_first_vertical.py` in worktree
  `messy-slack-preprocessing-runner-20260725` — current raw provider-dict
  construction.
- `inside_success/preprocessing/contracts.py` in the same worktree — current
  stage-specific `ProviderDataAuthorizationV1`.
- `plan/second_brain/DOCUMENT_PREPROCESSING_EXECUTION_CONTRACT_2026-07-27.md`
  — current direct-provider CLI flags that this shared contract will replace.

## Boundaries and Responsibility

```text
application authorization/config
        |
        | OpenRouterRoutePolicyV1 + explicit model
        v
llm_client policy validation and call identity
        |
        | compiled OpenRouter provider object
        v
LiteLLM transport -> OpenRouter fixed-model provider routing
        |
        +--> typed no-compatible-route failure
        |
        `--> response -> local Pydantic validation
                         |
                         `--> existing generation evidence (optional/authorized)
```

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Caller | model choice, private-data authorization, allowed upstream set, task/trace/budget | OpenRouter payload construction, retry classification |
| Typed policy | validated routing intent and deterministic serialization | model selection, authorization, endpoint health |
| OpenRouter compiler | exact provider payload mapping and conflict rejection | provider inventory, provider ranking database |
| OpenRouter | current endpoint filtering, same-model upstream selection, transport rejection | local application authorization, Pydantic semantic validation |
| Error layer | precise non-retryable route-compatibility classification | guessing model quality or provider outage |
| Evidence layer | requested-policy digest, attempt outcome, actual upstream when authenticated evidence is requested | claiming actual upstream from requested provider names |

## Public Contract

Add this exact model to `llm_client/execution/call_contracts.py` and export it
from `llm_client/__init__.py`:

```python
class OpenRouterRoutePolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_providers: tuple[str, ...] | None = None
    data_collection: Literal["allow", "deny"] | None = None
    zero_data_retention: bool | None = None
    allow_provider_fallbacks: bool = True
    sort: Literal["price", "throughput", "latency"] | None = None
    require_parameters: Literal[True] = True
```

### Field rules

| Field | Rule | Compiled OpenRouter key |
| --- | --- | --- |
| `allowed_providers` | `None` omits provider pinning; otherwise non-empty, trimmed, case-insensitively unique strings | `only: list[str]` |
| `data_collection` | `None` preserves OpenRouter account/request default; private callers must explicitly use `deny` | `data_collection` |
| `zero_data_retention` | `None` preserves default; private callers must explicitly use `True` | `zdr` |
| `allow_provider_fallbacks` | permits OpenRouter to try another allowed upstream for the same fixed model | `allow_fallbacks` |
| `sort` | optional OpenRouter provider ordering; no client-side provider ranking | `sort` |
| `require_parameters` | literal `True`; callers cannot opt out | `require_parameters` |

Additional validation rules:

- reject an explicitly empty provider tuple;
- reject blank provider names;
- reject duplicate provider names using `casefold()` comparison;
- reject `data_collection="allow"` together with
  `zero_data_retention=True` as contradictory routing intent;
- preserve caller spelling/order in serialization;
- serialize tuples as JSON arrays;
- never include keys whose source value is `None`;
- never include secrets, prompts, or source text in the policy or its digest.

### Public keyword

Add `openrouter_route_policy: OpenRouterRoutePolicyV1 | None = None` to:

- `call_llm` and `acall_llm`;
- `call_llm_structured` and `acall_llm_structured`;
- `call_llm_with_tools` and `acall_llm_with_tools`; and
- `stream_llm` and `astream_llm`.

Tool wrappers pass it through to the text call. Batch calls inherit it from
their per-call kwargs. Embeddings and background Responses retrieval are out of
scope; supplying the keyword there is unsupported rather than silently ignored.

The public wrapper must pass this as an explicit named parameter through the
corresponding runtime implementation. Do **not** hide it in `**kwargs` or under
an underscore-prefixed key: current internal-kwarg stripping would remove it
before dispatch and current snapshot normalization would omit it. Each runtime
validates the object once and derives a canonical JSON dictionary with
`model_dump(mode="json")`. The snapshot builder and completion-kwargs builder
both receive that dictionary through explicit named parameters. A Pydantic
object must never reach LiteLLM.

### Compiler

Add pure helpers in `llm_client/utils/openrouter.py`:

```python
def compile_openrouter_route_policy(
    policy: OpenRouterRoutePolicyV1,
) -> dict[str, object]: ...

def apply_openrouter_route_policy(
    model: str,
    call_kwargs: dict[str, Any],
    policy_payload: Mapping[str, object] | None,
) -> None: ...
```

`apply_openrouter_route_policy` must:

1. return unchanged when `policy_payload` is absent;
2. validate `policy_payload` through
   `OpenRouterRoutePolicyV1.model_validate()`;
3. reject a non-OpenRouter route before provider dispatch;
4. reject an existing raw `provider` key;
5. assign the compiled dictionary to `call_kwargs["provider"]`; and
6. allow the existing `_enable_openrouter_inline_metadata()` logic to merge
   only `require_parameters=True` and trace metadata.

Change both `_prepare_call_kwargs()` and `_prepare_responses_kwargs()` to accept
`openrouter_route_policy_v1: Mapping[str, object] | None` explicitly. Apply the
policy after ordinary internal kwargs are stripped and `call_kwargs` is built,
but before `_enable_openrouter_inline_metadata()`. For Responses, apply it to
`resp_kwargs` at the equivalent point. Both paths must produce the identical
OpenRouter `provider` object. Prevalidate the complete primary/fallback model
chain once: when a policy is present every model leg must resolve to an
OpenRouter route. Do not discover this only after a fallback has already begun.

The existing function must continue rejecting
`provider.require_parameters=False` for raw compatibility calls.

### Error contract

Add:

```python
class LLMNoCompatibleRouteError(LLMCapabilityError):
    """The gateway found no endpoint satisfying the fixed model and constraints."""
```

Classification must happen before generic LiteLLM `NotFoundError` handling when
the sanitized provider error contains the case-insensitive phrase:

```text
no endpoints found that can handle the requested parameters
```

Do not classify every OpenRouter 404 this way. A missing model remains
`LLMModelNotFoundError`. `LLMNoCompatibleRouteError` is non-retryable under the
existing retry policy and remains eligible for an explicit caller-supplied
different-model fallback only under existing fallback semantics.

The attempt diagnostic may record:

- exception class chain;
- HTTP status;
- gateway/provider request IDs;
- error code;
- fixed sanitized reason code `no_compatible_route`; and
- route-policy SHA-256.

It must not persist the prompt, response body, schema contents, source fields,
or authorization contents.

### Snapshot and replay

The canonical policy dictionary is part of request identity. Update the current
snapshot schema rather than placing a Pydantic instance in generic kwargs.

Required behavior:

- snapshot stores `openrouter_route_policy_v1` under request control;
- cache/fingerprint identity changes when any policy field changes;
- replay reconstructs `OpenRouterRoutePolicyV1` and passes it through the same
  public call path;
- malformed or unknown policy fields fail before dispatch;
- old snapshots without the field remain replayable with `None`;
- no new snapshot version is required if the current typed schema permits an
  optional additive control; otherwise increment the version and preserve all
  existing version readers. Do not weaken validation to avoid a version bump.

`build_call_snapshot()` and the replay execution-policy model receive this as
an explicit optional field. Replay reconstructs the public Pydantic object
before invoking the public API; it must not inject a raw provider dictionary.

## Runtime Rules

1. Validate model policy and route policy before any provider call.
2. Do not query `/endpoints` during a normal call.
3. Compile exactly once per provider attempt from the retained canonical policy.
4. Apply the same policy to every retry of the same model.
5. A model fallback receives the same OpenRouter policy only if its route is
   also OpenRouter; otherwise fail locally instead of silently dropping policy.
6. A no-compatible-route result terminates retries for that model immediately.
7. Actual upstream identity is observed only from OpenRouter response/generation
   evidence, never inferred from `allowed_providers`.
8. Local response-schema and Pydantic validation remain unchanged.
9. Compare an observed `provider_name` to `allowed_providers` using trimmed
   `casefold()` equality. Do not treat endpoint tags or model prefixes as the
   provider identity.

## Compatibility and Migration

### Compatibility window

- Existing calls with no typed policy behave exactly as before.
- Existing raw `provider` kwargs continue to work temporarily.
- Supplying both surfaces is a local configuration error; there is no merge or
  precedence rule.
- The broad provider-kwargs escape hatch is not removed in this plan because it
  may carry OpenRouter features not represented by V1.
- Deprecation may begin only after the inventory in WU-336-04 identifies every
  maintained caller and proves an equivalent typed representation.

### Inside Success integration

The consumer must replace `_provider_preferences()` with a function returning
`OpenRouterRoutePolicyV1`. Do not edit or regenerate a private authorization
receipt automatically.

For its current V1 singleton authorization, construct:

```python
OpenRouterRoutePolicyV1(
    allowed_providers=(authorization.upstream_processor,),
    data_collection="deny",
    zero_data_retention=True,
    allow_provider_fallbacks=False,
)
```

This preserves current authorization semantics but will still fail when the
authorized singleton has no compatible route. Supporting an authorization for
several upstream processors requires a separately reviewed
`ProviderDataAuthorizationV2`; that is an authorization-contract decision, not
something Plan #336 may invent or self-approve.

The first real private call may run only when the existing authorization
validates and its authorized processor currently yields a compatible route. If
not, stop with `authorized_upstream_has_no_compatible_route` and report the
exact new authorization decision required. Do not broaden `allowed_providers`
in code.

## Fixtures and Test Matrix

### Positive fixtures

1. A policy with one provider, `deny`, ZDR, no provider fallback, and no sort
   compiles to exactly:

   ```json
   {
     "only": ["ExampleProvider"],
     "data_collection": "deny",
     "zdr": true,
     "allow_fallbacks": false,
     "require_parameters": true
   }
   ```

2. A policy without `allowed_providers` omits `only` and lets OpenRouter select
   a compatible same-model upstream under the remaining constraints.
3. Sync and async structured calls send the same compiled provider object.
4. A replay sends the same canonical policy as the original call.

### Negative fixtures

- empty provider tuple;
- blank or duplicate provider names;
- contradictory `data_collection="allow"` plus ZDR;
- `require_parameters=False` in a mapping;
- unknown policy field;
- typed policy plus raw `provider` kwargs;
- typed policy on a direct-provider or agent-SDK route;
- fallback chain mixing OpenRouter and non-OpenRouter while policy is present;
- OpenRouter compatible-route 404 phrase;
- ordinary model-not-found 404;
- malformed policy in a replay snapshot; and
- diagnostic summary containing prompt or authorization material.

## Required Tests

### New and modified tests (write failing assertions first)

| Test file | Required test behavior |
| --- | --- |
| `tests/test_provider_kwargs.py` | exact policy compilation in Completions and Responses; `None` omission; invalid providers; raw/typed conflict; non-OpenRouter rejection; installed LiteLLM preserves the compiled object |
| `tests/test_errors.py` | compatible-route phrase maps to `LLMNoCompatibleRouteError`; ordinary missing-model 404 remains `LLMModelNotFoundError` |
| `tests/test_client.py` | compatible-route failure receives one attempt; mixed OpenRouter/direct fallback chain fails before dispatch when policy is present |
| `tests/test_structured_runtime.py` | sync and async native-schema attempts receive the same compiled provider policy |
| `tests/test_observability_replay.py` | snapshot records canonical policy; replay reconstructs the Pydantic policy; policy mutation changes identity; old snapshots remain readable |
| `tests/test_structured_attempts.py` | failed attempt records the typed failure class and bounded reason without content leakage |
| `tests/test_models.py` or `tests/test_structured_capability_registry.py` | model capability remains declared but is not presented as route-availability evidence |

### Existing gates

```bash
./.venv/bin/python -m pytest -q \
  tests/test_provider_kwargs.py \
  tests/test_errors.py \
  tests/test_client.py \
  tests/test_structured_runtime.py \
  tests/test_observability_replay.py \
  tests/test_structured_attempts.py \
  tests/test_models.py \
  tests/test_structured_capability_registry.py
python scripts/meta/generate_api_reference.py --write
python scripts/meta/generate_api_reference.py --check
python scripts/meta/validate_relationships.py --strict
make check
```

## Files Affected

### WU-336-01 — shared-client vertical

- `llm_client/execution/call_contracts.py` — add typed policy.
- `llm_client/utils/openrouter.py` — add pure compiler and application seam.
- `llm_client/core/client.py` — public keyword on covered call surfaces.
- `llm_client/execution/text_runtime.py` — retain canonical policy through call
  identity and attempts.
- `llm_client/execution/structured_runtime.py` — same for structured calls.
- `llm_client/execution/stream_runtime.py` — same for streaming calls.
- `llm_client/execution/completion_runtime.py` — apply the policy before current
  OpenRouter metadata/parameter normalization.
- `llm_client/execution/responses_runtime.py` — apply the same policy before
  current OpenRouter metadata/parameter normalization on Responses calls.
- `llm_client/core/errors.py` — add and classify the typed route error.
- `llm_client/observability/replay.py` — snapshot/replay policy.
- `llm_client/observability/attempt_diagnostics.py` and, only if required by
  current diagnostic construction, its producing runtime seam — bounded reason
  code and policy digest.
- `llm_client/__init__.py` — public exports.
- `tests/test_provider_kwargs.py` — compiler and conflict tests.
- `tests/test_errors.py` — route-vs-model 404 classification.
- `tests/test_client.py` — retry/fallback behavior.
- `tests/test_structured_runtime.py` — sync/async native-schema parity.
- `tests/test_observability_replay.py` — snapshot and replay.
- `tests/test_structured_attempts.py` — one-attempt diagnostic lifecycle.
- `docs/API_REFERENCE.md` — regenerate, never hand-edit.
- `docs/guides/model-selection.md` — model capability versus route readiness.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` — narrow
  amendment recording typed policy compilation; preserve its no-live-registry
  decision.
- `scripts/relationships.yaml` — add read-gate/code-doc edges if required by
  the repository validator; regenerate `AGENTS.md` only through its generator.

### WU-336-02 — Inside Success integration

This unit executes in the existing Inside Success preprocessing branch only
after its claim is available or explicitly handed off.

- `inside_success/preprocessing/run_first_vertical.py` — consume the public
  typed policy and remove raw dictionary construction.
- `inside_success/preprocessing/first_vertical.py` — remove CLI projection of
  raw provider flags where the model call is in-process; if a subprocess seam
  remains, pass a versioned JSON policy artifact rather than five independent
  flags.
- `inside_success/preprocessing/contracts.py` — no authorization broadening;
  change only if serialization needs to name the shared policy contract.
- `tests/preprocessing/test_first_vertical.py` — exact policy construction and
  fail-closed authorization tests.
- `tests/preprocessing/test_development_slice.py` — retained authorization
  coverage.
- `plan/second_brain/DOCUMENT_PREPROCESSING_EXECUTION_CONTRACT_2026-07-27.md`
  — replace raw OpenRouter flag instructions with the shared policy.

### Later migration inventory

Only paths found by a fresh deterministic inventory may enter WU-336-04. Do not
predeclare or edit arbitrary consumer repositories.

## Plan

### Execution order

Execute the work units in this order:

1. Complete and accept WU-336-01, the shared-client vertical.
2. Hand the accepted shared revision to WU-336-02 before doing broad parity or
   migration cleanup; this is the shortest path back to real preprocessing.
3. Complete WU-336-03 after WU-336-01 without blocking WU-336-02.
4. Begin WU-336-04 only after both the real consumer vertical and covered-call
   parity are accepted.

The detailed evidence-first steps, commands, and done conditions follow in each
unit. Passing one internal helper test does not permit skipping the real
structured-call probe or the Inside Success integration boundary.

### WU-336-01 — Typed policy through a real structured call

**Execution class:** independently executable  
**Availability:** ready for execution after this plan revision is adopted  
**Profile:** standard

**Objective:** Implement the complete shared boundary from typed policy through
compiled provider payload, snapshot/replay, precise failure, and one non-private
live structured route probe.

**Evidence-first order:** 

1. Add failing pure contract/compiler tests.
2. Add failing error-classification and no-retry tests.
3. Add failing sync/async structured snapshot/replay tests.
4. Implement the Pydantic policy and pure compiler.
5. Thread the canonical policy through covered public/runtime paths.
6. Implement error and diagnostic behavior.
7. Regenerate public API docs.
8. Run focused tests.
9. Run the full repository check.
10. Run one bounded non-private live probe and fetch actual generation evidence.
11. Re-run the controlled incompatible-route negative.
12. Commit one coherent `[Plan #336]` slice.

**Focused commands:**

```bash
./.venv/bin/python -m pytest -q \
  tests/test_provider_kwargs.py \
  tests/test_errors.py \
  tests/test_client.py \
  tests/test_structured_runtime.py \
  tests/test_observability_replay.py \
  tests/test_structured_attempts.py
python scripts/meta/generate_api_reference.py --write
python scripts/meta/validate_relationships.py --strict
make check
```

The live probe must use a trivial public string, a two-field Pydantic response,
`num_retries=0`, a finite timeout/logical timeout, an explicit budget, and a
fresh trace. It must not contain Slack, project, customer, or authorization
content. Persist only the existing privacy-bounded trace and generation
evidence.

**Done when:** all deterministic checks pass; the live probe returns validated
JSON through an allowed provider; actual upstream evidence is retained; and the
incompatible-route fixture produces exactly one non-retryable
`LLMNoCompatibleRouteError` attempt.

### WU-336-02 — Inside Success preprocessing consumer

**Execution class:** independently executable after WU-336-01  
**Availability:** unavailable while the active Inside Success preprocessing
claim owns the listed paths  
**Profile:** controlled because private Slack may cross an external processor

**Objective:** Replace application-built provider preferences with the shared
policy and complete the existing development preprocessing call without
changing the semantic prompt, schema, partition, source, or evaluation rules.

**Evidence-first order:**

1. Record current branch, package pin, dirty files, authorization digest, and
   prior failing trace ID without copying private content.
2. Add failing tests proving the runner constructs the exact typed policy and
   never emits the five raw provider CLI flags.
3. Update only the route-policy boundary.
4. Run preprocessing focused tests.
5. Install/pin the accepted WU-336-01 revision through the consumer's declared
   dependency mechanism.
6. Run one non-private route probe from the consumer environment.
7. Validate the private provider authorization without printing its contents.
8. If the authorized singleton is route-compatible, run the existing bounded
   development call once. If not, stop with the named authorization blocker.
9. Inspect the exact retained trace before making any provider/model claim.
10. Continue the already-authorized preprocessing vertical only if this routing
    boundary succeeds.

**Focused commands:**

```bash
./.venv/bin/python -m pytest -q \
  tests/preprocessing/test_first_vertical.py \
  tests/preprocessing/test_development_slice.py
```

The exact real-run command remains owned by the active Inside Success execution
contract. Do not copy a private path or secret into this shared plan.

**Done when:** the consumer contains no raw provider-dict builder for this call;
tests pass; the exact accepted `llm_client` revision is pinned; and either the
real development preprocessing call succeeds with a retained trace or the unit
stops truthfully on `authorized_upstream_has_no_compatible_route`.

### WU-336-03 — Covered-call parity and documentation cleanup

**Execution class:** independently executable after WU-336-01  
**Availability:** blocked dependency  
**Profile:** standard

Verify text, tools, streaming, async, and batch-through-child-call parity. Add
only missing tests or mechanical pass-through repairs. Embeddings remain out of
scope and must be documented as such. This unit must not delay WU-336-02.

**Done when:** every advertised covered call surface has a positive compiler
test and a non-OpenRouter negative; generated API docs and model-selection
guidance agree; full checks pass.

### WU-336-04 — Maintained-caller inventory and staged migration

**Execution class:** deferred  
**Availability:** not applicable until WU-336-02 and WU-336-03 are accepted

Run deterministic `rg`/registration-audit inventory across maintained
Brian-owned consumers for raw OpenRouter `provider` dictionaries and equivalent
CLI flags. Classify each occurrence:

- exactly representable by V1 — migrate in a separately claimed repository
  unit;
- uses unsupported but legitimate OpenRouter capability — retain raw kwargs and
  record the missing typed field;
- dead/generated/vendor/test-only — do not migrate blindly; disposition it;
- private authorization policy — do not convert without its owning decision.

Only after every maintained occurrence has a disposition may a later plan
deprecate raw `provider` kwargs. Deletion is not authorized by Plan #336.

## Acceptance Criteria

- [ ] AC-336-01: `OpenRouterRoutePolicyV1` rejects unknown, blank, duplicate,
  empty, and `require_parameters=False` inputs.
- [ ] AC-336-02: compiler output exactly matches the documented mapping and
  omits `None` fields.
- [ ] AC-336-03: typed policy plus raw `provider` kwargs fails before dispatch.
- [ ] AC-336-04: typed policy on a non-OpenRouter route fails before dispatch.
- [ ] AC-336-05: sync and async structured calls send identical routing policy.
- [ ] AC-336-06: policy changes alter snapshot/replay identity; old snapshots
  remain valid.
- [ ] AC-336-07: compatible-route 404 and model-not-found 404 are distinct.
- [ ] AC-336-08: compatible-route failure is attempted once with no internal
  retry.
- [ ] AC-336-09: model-level capability docs explicitly disclaim route
  availability.
- [ ] AC-336-10: actual upstream identity is read from authenticated generation
  evidence, not inferred.
- [ ] AC-336-11: one non-private live structured call validates through an
  allowed upstream.
- [ ] AC-336-12: Inside Success uses the typed policy or stops on the exact
  active-claim/authorization blocker; no provider list is broadened by code.
- [ ] AC-336-13: focused tests, relationship validation, generated API check,
  type check, lint, and full suite pass at the accepted shared-client revision.
- [ ] AC-336-14: no secret, private source text, authorization payload, or raw
  provider response is added to Git.

## Stop Conditions

Stop implementation and report the exact evidence when:

- another claim owns a listed write path;
- ADR 0016 or a newer accepted ADR contradicts a proposed runtime behavior;
- OpenRouter's documented provider keys differ from the frozen compiler mapping;
- the installed LiteLLM strips or rewrites a compiled routing field;
- replay cannot preserve the policy without a snapshot schema migration;
- error classification requires persisting a raw provider response;
- the live probe selects an upstream outside `allowed_providers`;
- the consumer's authorization does not cover the requested upstream;
- the consumer requires authorization broadening rather than a code change; or
- a proposed fix mentions the one DeepSeek trace more than the general
  fixed-model/constraint incompatibility contract.

Do not respond to a stop condition by adding endpoint scraping, hard-coding a
currently healthy provider, relaxing ZDR/data rules, enabling Auto Router,
raising retries, changing the model, or changing preprocessing semantics.

## Recovery and Rollback

- All shared-client changes are additive until caller migration.
- Reverting WU-336-01 restores raw provider kwargs behavior for existing calls.
- A migrated consumer may revert to its prior raw dictionary only as an
  explicit rollback to the preserved revision; do not retain both active paths.
- Live probes use new trace IDs and no private inputs.
- Failed private calls preserve existing trace/readout artifacts and never
  overwrite a run root.
- No database migration, deployment, package publication, or credential change
  is authorized by this plan.

## Concerns and Non-Claims

| Concern | Disposition |
| --- | --- |
| OpenRouter endpoint availability changes | Accepted moving dependency; provider routes at request time and failures are typed |
| Public `/endpoints` metadata could preflight calls | Deferred; conflicts with the no-live-capability-registry boundary and cannot eliminate dispatch races |
| Exact upstream authorization may prevent fallback | Preserved intentionally; authorization owner must approve a larger set |
| One phrase drives error classification | Mitigated by a narrow failure-family test plus a control proving ordinary 404 remains model-not-found |
| Raw provider kwargs remain | Accepted compatibility window; inventory before deprecation |
| Policy name is OpenRouter-specific | Intentional; no false portability claim |
| This may delay preprocessing | Mitigated by ordering WU-336-02 before broad parity/migration cleanup |

## Next-Skill Handoff

The validated proposed handoff is
`docs/plans/supporting/336_next_skill_handoff.json`. Its source digests bind the
implementer to this exact plan and work graph. Any material plan edit requires
regenerating that handoff before execution readiness is claimed.
