# ADR 0016: Provider Capability and Vendor Telemetry Boundary

Status: Accepted
Date: 2026-07-22
Applies to: Plan #110

## 2026-08-05 Amendment: Provider Exclusion and Malformed-JSON Recovery

Plan #349 adds `ignored_providers` to `OpenRouterRoutePolicyV1` and compiles it
to OpenRouter's native `provider.ignore` field. Exclusions are explicit
caller-owned routing intent, retained in call snapshots and replay identity;
they do not create a shared endpoint-health database. Allowed and ignored
provider sets must be non-empty, duplicate-free, and disjoint when supplied.

A syntactically malformed structured response remains retryable only within the
caller's existing retry, deadline, and budget bounds. The next attempt receives
a concise instruction to return only valid JSON matching the supplied schema.
This recovery does not retry a response that already satisfies the Pydantic
contract, and therefore does not move application semantic judgment into the
shared runtime.

## 2026-08-04 Amendment: GPT-5.4 Ban and Luna Default

Plan #348 hard-blocks every GPT-5.4-family route before dispatch, including
raw, OpenRouter, Mini/Nano, fallback, and Codex aliases. GPT-5.4 is removed
from the exact execution allowlist, capability table, packaged registry, and
maintained workflow defaults. GPT-5.6 Luna becomes the shared execution default
and replaces GPT-5.4 on maintained Codex workflow surfaces. When Luna cannot
satisfy a required execution contract, callers must select and justify an
explicit non-GPT-5.4 route; they may not silently revive GPT-5.4.

## 2026-08-17 Amendment: Compatibility-Aware Workload Routing

Plan #361 replaces the unsafe global Codex subscription default with an
explicit `WorkloadRouteContext` and `resolve_workload_route()` contract. Codex
subscription capacity is chosen only for a declared compatible interactive or
trusted-private workload with supported subscription authentication and known
available included capacity. Managed automation, service/API requirements, and
unsupported subscription authentication select the direct OpenAI API route.

OpenRouter remains an explicit edge route: a required router capability
(including non-OpenAI model access, multi-provider routing, or provider
controls) or a current recorded value comparison can select it. Subscription
exhaustion fails locally until the caller records whether paid Codex credits,
direct OpenAI API, or OpenRouter won the live comparison; it is never automatic
OpenRouter overflow. The legacy `DEFAULT_EXECUTION_MODEL` remains only for
unmigrated callers and does not express the new workload-routing policy.

## 2026-07-31 Amendment: OpenRouter Exact-Response Cache Policy

Plan #347 extends `OpenRouterRoutePolicyV1` with an explicit, default-off
exact-response cache mode and an optional TTL. `enabled` compiles to
`X-OpenRouter-Cache: true`; `refresh` additionally clears and replaces only the
matching entry; `disabled` sends the explicit provider opt-out when a typed
policy is present. TTLs fail locally outside OpenRouter's documented 1–86,400
second range.

Response caching retains generated content at OpenRouter's edge for the selected
TTL, so enabled and refresh modes conflict locally with
`zero_data_retention=True`. Raw response-cache headers also conflict with a
typed policy: callers may use the broad raw-header escape hatch only when they
do not claim typed cache governance.

OpenRouter hashes the complete provider request body. Therefore a cache-enabled
call retains `llm_client` task/trace custody locally but does not project its
unique per-call identity into OpenRouter's request-body Broadcast `trace` field.
An explicit caller-owned Broadcast trace is rejected for a cache-enabled call
rather than silently defeating reuse. Attribution and route-metadata headers do
not enter OpenRouter's cache key, although a cache hit does not return stale
router metadata.

This is distinct from provider prompt caching and from durable consumer stage
artifacts. OpenRouter does not coalesce concurrent misses and may evict entries;
consumers remain responsible for content-addressed resumability, single-flight,
schema and algorithm invalidation, and source-custody rules. Local/provider
usage telemetry remains evidence of billed versus cached tokens; one bounded
live repeated-call probe is required before a consumer advertises the route as
working.

## 2026-07-27 Amendment: Typed OpenRouter Route Policy

Plan #336 adds `OpenRouterRoutePolicyV1` as the supported named public
contract for stable OpenRouter provider-routing requirements: provider
allowlists, data-collection mode, zero-data-retention, same-model provider
fallback permission, sorting, and `require_parameters=true`. `llm_client`
compiles this object into OpenRouter's native `provider` payload, retains the
canonical policy in call snapshots, and rejects ambiguous raw `provider` kwargs
when the typed policy is present.

This amendment does not create a local endpoint inventory or preflight call.
OpenRouter remains the runtime authority on whether a current endpoint satisfies
the fixed model and requested constraints. An OpenRouter response that no
endpoint can satisfy those constraints is a non-retryable
`LLMNoCompatibleRouteError`, not evidence that the model is absent.

The policy constrains routing only. It does not authorize a provider to receive
private source fields; callers remain responsible for an authorization covering
every allowed upstream processor. Every resolved primary/fallback model leg
must be an OpenRouter route when this policy is used, and embeddings remain
outside the typed-policy surface.

## 2026-07-23 Amendment: Explicit Reasoning Policy

Plan #117 makes reasoning selection an explicit pre-dispatch policy for exact
allowlisted routes that expose configurable effort. Omission is no longer
interpreted as provider default. The caller must resolve an effort, including
`none` for explicit off where supported; unsupported values, forbidden off
states, and incompatible fallback chains fail locally.

Reviewed per-model capability metadata is enforcement authority. LiteLLM and
provider transports still own payload translation. `llm_client` does not fetch
mutable provider metadata during calls or implement provider-specific
application payloads. The resolved policy is bound into routing evidence,
replay identity, and cache identity.

Direct Gemini's prior automatic thinking default is superseded for governed
reasoning-policy calls. Codex receives the same normalized decision through its
SDK-specific `model_reasoning_effort` transport rather than choosing `high`
when omitted.

## 2026-07-23 Amendment: Exact Model Execution Allowlist

Plan #115 supersedes this ADR's ban-oriented model-selection policy while
preserving its provider-capability and telemetry decisions.

`llm_client` evaluates every canonical primary/fallback chain against one exact
shared allowlist before dispatch. DeepSeek V4 Flash is the sole
no-justification default. Every other allowed route requires a non-empty
`model_justification`, which is retained in the routing trace and replayable
call snapshot. A justification cannot authorize an unlisted model. The former
`compatibility` mode was removed by Plan #116 and is now rejected.

GPT-5 Mini and GPT-5.1 Mini are not allowlisted and are also hard-blocked,
together with Codex Mini routes.

The statement below that normalized public controls are forwarded “without a
model-family allowlist” refers only to capability-specific branching after
model authorization. It no longer means arbitrary models may execute.

## Context

`llm_client` exists so applications can use provider capabilities without
growing provider branches in every consumer. Two gaps made that boundary less
general than intended:

1. the public `reasoning_effort` option was forwarded only for hard-coded
   OpenAI and Anthropic families, even though OpenRouter and DeepSeek expose the
   same normalized control; and
2. required `task` and `trace_id` metadata reached local observability and
   LiteLLM callbacks, but not OpenRouter's native Broadcast trace envelope.

OpenRouter already normalizes reasoning controls and can broadcast request
traces to established observability backends. LiteLLM already owns commodity
transport normalization. Reimplementing either facility would add a second
capability matrix and a second telemetry exporter.

At the same time, vendor telemetry cannot replace local evidence. It does not
cover direct providers, workspace-agent SDKs, cache hits, pre-dispatch policy
failures, local schema validation, retry/fallback dispositions, or local budget
enforcement.

The user also requires Opus-family models to be unavailable through
`llm_client`, including workspace-agent aliases. A ban that applies only to raw
chat routes would be misleading. OpenRouter Auto Router, presets, and provider
fallback arrays can select a final model after the primary model string is
checked, so opaque model selection is also inside the ban's threat model.

## Decision

1. Normalized public controls are forwarded without a model-family allowlist.
   The selected provider/transport remains responsible for accepting or
   rejecting the control. `llm_client` must not silently discard it.
   When an installed LiteLLM capability table lags a documented OpenRouter
   normalized control, the OpenRouter transport declares that control through
   LiteLLM's `allowed_openai_params` compatibility seam and sets
   `provider.require_parameters=true`. A caller may still choose provider
   sorting and fallback policy, but may not opt into silently ignored controls.
2. The existing broad provider-kwargs surface remains the escape hatch for new
   provider features that do not yet have a normalized public option.
3. For OpenRouter calls, `llm_client` projects its required `task` and
   `trace_id` into OpenRouter's `trace` object without overwriting caller-owned
   trace fields. Account-side Broadcast configuration remains outside the
   library.
4. Local JSONL/SQLite evidence remains authoritative for `llm_client` execution
   semantics. OpenRouter logging/Broadcast and LiteLLM callbacks are optional,
   complementary projections.
5. Opus-family model IDs and aliases are hard-blocked before dispatch in every
   execution mode. The model registry, model-policy audit, public examples, and
   workflow defaults must not select Opus.
6. Every resolved fallback leg is checked. OpenRouter Auto Router, presets, and
   the auto-router plugin are rejected because their candidate sets are not
   locally inspectable; provider `models`/`fallbacks` arrays are accepted only
   when they contain no banned or opaque selector. Fixed-model provider sorting
   remains supported. Account Guardrails are recommended defense in depth, not
   a substitute for local enforcement.
7. Claude workspace-agent defaults that previously selected Opus move to
   Sonnet. The ordinary `max_intelligence` tier selects the best remaining
   non-banned registered candidate under its existing ordering; this decision
   does not create a special replacement route.

## Borrow Versus Build

- **Borrow:** OpenRouter reasoning parameters, OpenRouter Broadcast/OTLP
  exporters, and LiteLLM provider transport.
- **Build:** small normalization/projection seams, invariant enforcement, local
  evidence, and deterministic contract tests.
- **Do not build:** another provider capability database, another OTLP
  exporter, or an OpenRouter-specific application client.

## Consequences

Positive:

1. Newly standardized controls can work without adding model-family branches.
2. OpenRouter users can enable existing observability destinations without
   application instrumentation while retaining local forensic evidence.
3. Opus cannot be reached indirectly through agent aliases, defaults,
   fallbacks, Auto Router, or presets.

Negative:

1. An unsupported normalized control now fails at the provider instead of being
   silently ignored.
2. Local and vendor traces may both exist and need a shared trace identifier.
3. Existing workflows that depended on Opus change model behavior when their
   defaults move to Sonnet.
4. Callers cannot use account-side model selectors while the non-overridable
   local model ban is active; they must request an explicit model.

## Testing Contract

1. Sync and async call preparation must forward DeepSeek/OpenRouter
   `reasoning_effort`.
2. OpenRouter calls must merge `task` and `trace_id` into Broadcast metadata
   while preserving explicit caller fields; non-OpenRouter calls must not gain
   the vendor envelope.
3. Raw Opus IDs, OpenRouter Opus IDs, `claude-code/opus`, Opus fallback legs,
   Auto Router, and presets must all fail before provider or agent dispatch.
4. Opus must not appear as a selectable packaged-registry model or workflow
   default.
5. Local observability tests remain unchanged and green.
6. OpenRouter reasoning controls must set `provider.require_parameters=true`,
   preserve other provider-routing fields, and reject an explicit false value.

Plan 354 changes only local structured terminal-lifecycle ownership. Provider
selection, capability enforcement, OpenRouter policy, vendor telemetry, model
allowlisting, and explicit reasoning behavior remain unchanged; composed
sync/async structured controls pass.
