# Model Selection

`llm_client` model selection has three separate decisions:

1. **Execution policy** — every call is checked against the exact shared
   allowlist before dispatch.
2. **Raw model tier** — task-shape, latency, and reasoning tradeoff for ordinary
   text or structured-output calls. Cost is observed, not a launch gate.
3. **Execution mode** — whether the call needs a workspace-agent SDK lane with
   side effects, tools, and repository context.

New and migrated production callers use:

```python
result = call_llm(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    reasoning_effort="none",
    task="bounded_decision",
    trace_id=trace_id,
    max_budget=0.05,
)
```

DeepSeek V4 Flash is the only no-justification default. Any other allowed
canonical route requires a non-empty `model_justification`; the decision is
retained in both the routing trace and replayable call snapshot. A justification
cannot authorize a route absent from the allowlist. GPT-5 Mini, GPT-5.1 Mini,
GPT-5.4 Mini, and Codex Mini routes are intentionally absent and therefore fail
before provider dispatch.

GPT-5.5 is retired: direct, Pro, and OpenRouter aliases are absent from the
allowlist and registry and are hard-blocked before provider dispatch.

Enforcement is unconditional. `model_policy="enforce_allowlist"` remains an
accepted explicit value for replay clarity, but omitting it has the same
fail-closed behavior. The former `compatibility` value is rejected.

Do not use agent SDK models merely because they are “smarter.” Use them when
the workflow needs workspace side effects:

```python
result = call_llm(
    "codex/gpt-5.4",
    messages,
    execution_mode="workspace_agent",
    reasoning_effort="medium",
    task="repo_edit",
    trace_id=trace_id,
    max_budget=5.00,
)
```

## Provider Capabilities

Reasoning-configurable routes require a reviewed explicit effort. Omission is
rejected before cache lookup or provider dispatch. For example, DeepSeek V4
Flash xhigh reasoning through OpenRouter is the ordinary model plus an effort setting,
not a second model ID:

```python
result = call_llm_structured(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    response_model=Decision,
    reasoning_effort="xhigh",
    task="bounded_decision",
    trace_id=trace_id,
    max_budget=0.05,
)
```

Provider capability forwarding remains independent of the execution allowlist.
For an allowed route, `llm_client` forwards normalized controls without
model-family-specific branches.
OpenRouter transport explicitly admits those documented controls through
LiteLLM even when the installed LiteLLM capability table lags the provider.
It also requires a provider route that supports the controls. Unsupported
controls fail at the transport/provider boundary rather than being silently
discarded.

New provider options do not require a new `llm_client` feature merely to pass
through. Public calls already accept broad provider kwargs. Promote an option
to a named public control only when it has stable cross-provider meaning,
requires shared validation, or must be bound into replay/policy.

### OpenRouter routing settings

Provider selection and model selection are different:

- Provider sorting such as OpenRouter's balanced default may choose which
  upstream serves a fixed explicit model. `llm_client` preserves these settings.
- Auto Router, presets, and the auto-router plugin may choose a different final
  model. They are rejected because `llm_client` cannot inspect the account-side
  candidate set before enforcing its non-overridable model bans.
- Provider `models` and `fallbacks` arrays are checked for banned or opaque
  candidates before dispatch.
- An OpenRouter Guardrail model allowlist is useful defense in depth. Do not use
  `anthropic/*` when Opus must be excluded: the wildcard includes every
  Anthropic model. Prefer explicit approved model IDs.

An account-level default model does not replace an explicit model in a normal
`llm_client` call. Keep explicit model selection in code/config and use
OpenRouter provider routing only to choose a compatible endpoint.

For stable OpenRouter route constraints, use the typed policy instead of
constructing a raw `provider={...}` payload:

```python
from llm_client import OpenRouterRoutePolicyV1, call_llm_structured

result, call = call_llm_structured(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    response_model=Decision,
    openrouter_route_policy=OpenRouterRoutePolicyV1(
        allowed_providers=("authorized-upstream",),
        data_collection="deny",
        zero_data_retention=True,
        allow_provider_fallbacks=False,
    ),
    reasoning_effort="none",
    task="bounded_decision",
    trace_id=trace_id,
    max_budget=0.05,
)
```

The policy is validated locally, compiled once into OpenRouter's provider
controls, and retained in replay identity. It cannot be combined with raw
`provider` kwargs, and every resolved fallback leg must remain on OpenRouter.
`LLMNoCompatibleRouteError` means the fixed model has no current endpoint that
satisfies the requested policy; it is not a model-not-found error and is not
retried within the same call.

This object does not grant permission to transmit private data. A caller that
uses `allowed_providers` must still have an explicit authorization for every
listed upstream processor and source field. The client does not query a live
endpoint registry before a call, so model-level structured capability remains
separate from policy-constrained route availability.

## Local and Vendor Observability

OpenRouter can log inputs/outputs and [Broadcast traces to existing
observability platforms](https://openrouter.ai/docs/guides/features/broadcast/overview).
For OpenRouter calls, `llm_client` automatically projects its required
`task`/`trace_id` into the provider's `trace` envelope while preserving any
caller-supplied trace hierarchy. Destinations, sampling, and privacy remain
OpenRouter workspace settings.

This complements rather than replaces local JSONL/SQLite evidence. Local
evidence also covers direct providers, workspace-agent SDKs, cache hits,
pre-dispatch policy failures, retries/fallbacks, local schema validation, and
budget enforcement. Use the shared trace ID to join the two views; do not build
another provider-specific exporter inside `llm_client`.

For ordinary model selection during migration, prefer tier selectors. Under
`model_policy="enforce_allowlist"`, the selector's complete resolved chain must
be allowed, and every non-default route requires `model_justification`:

| Selector | Default model | Use for | Do not use for |
|---|---|---|---|
| `ultra_fast_low_intel` | Mercury 2 | tiny rewrites, routing, low-stakes transforms | judgment, synthesis, policy |
| `ultra_cheap_low_intel` | GPT-5 nano | disposable low-stakes bulk work | correctness-sensitive work |
| `fast_cheap_mid` | DeepSeek V4 Flash | bulk structured work with a real reasoning floor | final review or high-stakes decisions |
| `fast_mid` | GPT-5.4 nano | latency-sensitive general work | deep reasoning |
| `default_intelligent` | MiniMax-M3 | normal project default | workspace side effects |
| `fast_intelligent` | GLM 5.2 | stronger reasoning without huge latency | final “best possible” escalation |
| `very_intelligent` | Grok 4.5 | difficult semantic judgment, coreference, ontology authoring, and deep review | automatic bulk pipelines |
| `max_intelligence` | GPT-5.6 Sol through OpenRouter | explicit max-quality escalation | default routing |

Compatibility selectors such as `extraction`, `judging`, `synthesis`, and
`bulk_cheap` remain available so existing projects do not break. New code
should use the tier names above and keep task intent in the required
`task=` observability tag.

## Default Profiles

Select the smallest tier that matches the judgment required. These are defaults,
not cost approval gates:

| Application situation | Selector to request | Why |
|---|---|---|
| High-volume extraction or candidate generation | `fast_cheap_mid` | A reasoning-capable structured route for work where every output is subsequently validated or reviewed. |
| Ordinary extraction, classification, and structured reasoning | `default_intelligent` | The general project default when the task has normal ambiguity but not difficult document interpretation. |
| Ambiguous document meaning, cross-chunk coreference, semantic authoring, or substantive review | `very_intelligent` | The default for tasks where a wrong semantic interpretation is more costly than additional latency. |
| A named, exceptional quality escalation | `max_intelligence` | Use only when the calling plan records why the ordinary semantic-authoring tier is insufficient. |

Do not silently fall back between profiles. A caller may select another profile
explicitly in project configuration, and the selected route must be visible in
the call trace. A provider outage or route rejection is a failure to surface,
not permission to substitute a weaker semantic actor.

## Model Decision Card

Use six primary fields. Do not turn model selection into a large, weakly
weighted scorecard:

1. **Intelligence** — independent general-capability evidence at the exact
   reasoning effort, supplemented by task-specific evidence when it exists.
2. **Speed** — output tokens per second, plus end-to-end task latency when
   reasoning time is material.
3. **Cost** — current input/output price for the exact route and observed cost
   per completed task. Per-token price alone can hide reasoning verbosity.
4. **Structured output** — provider declaration plus local certification for
   the exact route and schema class. Declaration is not certification.
5. **Context window** — combined input/output limit for the exact route.
6. **Reliability** — retained local completion evidence for the exact route,
   task shape, and schema. Public uptime is useful context, not a substitute.

Everything else, including modalities, tool support, openness, cache policy,
and knowledge cutoff, is optional **miscellaneous** metadata unless the task
makes it a hard requirement. Every external value must retain its source,
reasoning effort, and observation date because model behavior and pricing move
quickly.

### Current reasoning-heavy shortlist

Observed 2026-07-28. Intelligence and speed are Artificial Analysis
Intelligence Index v4.1 and first-party/median-provider output speed at the
listed effort. Cost is the OpenRouter route's current USD input/output price
per million tokens. Context and declared structured capability come from the
OpenRouter models API. The final column is our retained local evidence, not a
public benchmark.

| Exact OpenRouter route | Intelligence / effort | Speed | Cost in/out | Context | Structured output and local reliability |
|---|---:|---:|---:|---:|---|
| `openrouter/deepseek/deepseek-v4-flash` | 40 / max | 116 tok/s | $0.14 / $0.28 | 1.05M | Declared; certified for one bounded extraction contract. Recent Process Tracing long strict-schema calls also produced validation and deadline failures, so do not generalize the certificate. |
| `openrouter/inception/mercury-2` | 21 | 987 tok/s | $0.25 / $0.75 | 128K | Declared; no retained local contract certificate. Use only for low-judgment work. |
| `openrouter/minimax/minimax-m3` | 44 | 91 tok/s | $0.30 / $1.20 | 1.05M | Declared; provider transport accepted one semantic-authoring schema, but local validation rejected the result. Not certified for that contract. |
| `openrouter/openai/gpt-5.6-luna` | 51 / max | 188 tok/s | $0.50 / $3.00 | 1.05M | Current strict native JSON-schema probe passed (`{"value": 1}`, 2026-07-31). The earlier large Process Tracing request remains a separate compatibility case, not a general route rejection. |
| `openrouter/qwen/qwen3.7-max` | 46 | 202 tok/s | $1.25 / $3.75 | 1.0M | Declared; no retained local contract certificate. |
| `openrouter/z-ai/glm-5.2` | 51 / max | 219 tok/s | $0.76 / $2.40 | 1.05M | Declared; no retained local contract certificate. Strong public value candidate, not yet a certified local default. |
| `openrouter/x-ai/grok-4.5` | 54 / high | 58 tok/s | $2.00 / $6.00 | 500K | Declared; local native-schema attempt reached the route but was capacity-blocked. No semantic certificate. |
| `openrouter/openai/gpt-5.6-terra` | 55 / max | 136 tok/s | $1.25 / $7.50 | 1.05M | Declared; certified for the retained DIGIMON planner contract. Independent comparison currently places Luna or Sol ahead of Terra on intelligence versus cost at every tested effort. |
| `openrouter/openai/gpt-5.6-sol` | 59 / max | 66 tok/s | $5.00 / $30.00 | 1.05M | Current strict native JSON-schema probe passed (`{"value": 1}`, 2026-07-31). The earlier large Process Tracing request remains a separate compatibility case, not a general route rejection. |

Sources: [Artificial Analysis methodology and v4.1](https://artificialanalysis.ai/articles/artificial-analysis-intelligence-index-v4-1),
[DeepSeek V4 Flash](https://artificialanalysis.ai/models/deepseek-v4-flash),
[Mercury 2](https://artificialanalysis.ai/models/mercury-2),
[MiniMax M3](https://artificialanalysis.ai/models/minimax-m3),
[GPT-5.6 family](https://artificialanalysis.ai/articles/gpt-5-6-has-landed),
[Qwen3.7 Max](https://artificialanalysis.ai/models/qwen3-7-max),
[GLM-5.2](https://artificialanalysis.ai/models/glm-5-2),
[Grok 4.5](https://artificialanalysis.ai/models/grok-4-5), and the
[OpenRouter models API](https://openrouter.ai/api/v1/models). Provider pages
linked in the route-evidence records below supply capability context. Prices
are snapshots, not durable constants.

### Selection guidance for research pipelines

- **High-volume bounded extraction:** DeepSeek V4 Flash at a reviewed effort
  when its exact route is completing the target schema; Luna is the next
  candidate after it is certified on that exact extraction contract.
- **Ordinary structured reasoning:** compare Luna and GLM 5.2 on the actual
  schema before changing a shared default. Public metrics make both plausible;
  they do not certify either route locally.
- **Consequential discriminator, mechanism, and final-critic judgments:** use
  GPT-5.6 Sol at high or max effort when the quality gain justifies latency and
  cost. Keep the number of such calls small rather than weakening the judgment.
- **Terra:** retain as an explicit certified route, but do not make it a default
  without task-specific evidence that overcomes its current public Pareto
  disadvantage.
- **Mercury 2:** speed-specialist only. Its public intelligence score does not
  support use for substantive causal interpretation or final review.

These are first-principles defaults informed by current public and route
evidence, not a claim that general leaderboards settle Process Tracing quality.
Task-specific comparisons become necessary only when two polished candidates
remain decision-equivalent after applying these constraints.

## Declared Capability vs. Certified Route

`structured_output: true` in the model registry means the model remains
eligible for maintained typed-output work through a governed client path. It
does not choose provider-native JSON Schema. The separate
`native_structured_output` value chooses transport for a curated route:
`true` permits native `json_schema`, `false` selects Instructor, and an omitted
value preserves legacy registry behavior by inheriting `structured_output`.

Neither field certifies every schema or parameter profile. A bounded retained
native success and a later no-compatible-endpoint result can both be true when
the contract or provider inventory differs. The conservative runtime default
must follow current general evidence without deleting the narrower historical
certificate.

Before a profile is advertised as runnable for a structured task, maintain a
route-certification record for the exact:

`model + provider route + execution mode + schema class`.

The record must show one retained real attempt that reached the provider,
accepted the schema, and returned parseable content. It must distinguish route
or transport failure from a semantic-quality failure. Until then, selection is
only a declared default and callers must fail loudly if the provider rejects
the route.

Ordinary OpenRouter inference requests inline router metadata and does not
block on the eventually consistent generation-history endpoint. Exact
endpoint-level certification is deliberately opt-in: set
`LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION=enabled` only for a bounded
certification run. A certification lookup enriches an already-successful call;
it is not part of model execution and must not be used as a quality verdict.

For small structured calls, the owning task profile must supply any required
technical output ceiling centrally and expose it in the call snapshot. Callers
must not invent one-off token caps; this is a provider-capacity setting, not a
cost authorization mechanism.

### Current Route Evidence

This table is the current operational answer to “can I use this model?” It is
not a quality leaderboard. A certification applies only to its named route and
schema class; do not transfer it to a different provider, response schema, or
task shape.

| Model route | Tier | Structured-route status | Observed evidence and use decision |
|---|---|---|---|
| `openrouter/deepseek/deepseek-v4-flash` | `fast_cheap_mid` | **Certified for one bounded extraction contract** | Plan 0147 retained a successful native-`json_schema` extraction with exact evidence offsets and no cache/fallback. It is the current default for high-volume bounded extraction, not a general semantic-quality winner. Evidence: `onto-canon6/docs/runs/plan0147/2026-07-16_functional_poc_v1.md`. |
| `openrouter/minimax/minimax-m3` | `default_intelligent` | **Transport reached; output contract not certified** | Plan 0141's provider accepted the structural schema and returned content, but local Pydantic/business validation rejected the monolithic response. This does not prove poor extraction quality, but it does mean MiniMax is not certified for that semantic-authoring schema. Use only after the selected task's smaller contract has a retained passing trace. Evidence: `onto-canon6/docs/runs/2026-07-14_plan0141_minimax_discovery_probe.md`. |
| `openrouter/x-ai/grok-4.5` | `very_intelligent` | **Native route reached; capacity blocked** | The Jane/Bob coreference request reached the native-schema route but OpenRouter returned HTTP 402 while reserving its default output allowance. This is neither a semantic failure nor a certification. Retry only after the task-profile output ceiling is wired. Evidence: `onto-canon6/docs/runs/2026-07-16_plan0141_coreference_vertical.md`. |
| `gemini/gemini-2.5-flash` | explicit route | **Unavailable in observed environment** | The Plan 0147 retry received a daily-quota exhaustion response. It produced no accepted semantic output and no capability conclusion. |
| GPT-5.5, direct or OpenRouter | historical only | **Hard-blocked before dispatch** | The retained direct strict-schema receipt remains historical transport evidence. New calls use the GPT-5.6 family. |
| direct `gpt-5.6` (Sol) | `max_intelligence` direct counterpart | **Certified for one bounded strict-schema contract** | Direct OpenAI Responses API returned schema-valid typed content. The provider-policy exact alias preserves this direct route even while the tier selector uses OpenRouter. This is route evidence, not semantic-quality certification. Evidence: `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md`. |
| direct `gpt-5.6-terra` | explicit manual selection | **Certified for one bounded strict-schema contract** | Same contract-tested direct Responses API route as Sol, retained as an explicit choice rather than a default. Evidence: `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md`. |
| `openrouter/openai/gpt-5.6-sol` (medium) | explicit manual selection | **Instructor default; bounded native certificate retained** | The OpenRouter native-`json_schema` route returned a validated Cybernetic Influence `resource_request_v1`, but the 2026-07-29 Process Tracing probe found no endpoint accepting its requested structured parameter profile. Shared auto mode now uses Instructor; the older certificate remains valid only for its named contract. Evidence: `docs/runs/2026-07-25_openrouter_gpt56_sol_authoring_schema_certification.md` and trace `process-tracing.sol-medium-capability-probe.20260730T000519Z`. |
| `openrouter/openai/gpt-5.6-terra` (medium) | explicit planner candidate | **Certified for the retained DIGIMON planner contract with the disjoint-union projection** | The endpoint rejected Pydantic's original `oneOf`; the provider-safe `anyOf` projection returned a sensible decision that validated against the unchanged local schema. Preferred current candidate for the main graph-planning decision, not a shared tier default. Evidence: `docs/runs/2026-07-21_openrouter_gpt56_planner_schema_compatibility.md`. |
| `openrouter/openai/gpt-5.6-luna` (medium) | explicit low-latency planner candidate | **Instructor default; bounded native certificate retained** | The DIGIMON planner contract passed in 4.321 seconds, but the 2026-07-29 Process Tracing probe found no endpoint accepting its requested structured parameter profile. Shared auto mode now uses Instructor; do not transfer either result across schemas. Evidence: `docs/runs/2026-07-21_openrouter_gpt56_planner_schema_compatibility.md` and trace `process-tracing.luna-medium-capability-probe.20260729T222353Z`. |

When a route changes status, update this table together with the retained run
record. A route may move from declared to certified only after a real call
returns parseable content under the named contract. A failed call must record
whether failure occurred before provider dispatch, at schema transport, at
provider capacity/quota, or during local contract validation; never label all
of these simply “model failure.”

Provider documentation is useful for deciding which route to register and
probe, but it does not certify a local route. GPT-5.6 Sol and Terra have
bounded direct-route evidence; Luna has one retained OpenRouter planner result.
None of those narrow contracts proves general task quality.

The enforced allowlist supersedes family-by-family bans for all callers.
Fable, Opus, GPT-5.5, GPT Mini, Codex Mini, unknown models, and opaque account-side
selectors are all unavailable because they are not exact allowlist entries.
Neither `model_justification` nor generic `model_override_acceptance` can
authorize an unlisted route.

## Should every project register through `llm_client`?

Yes for production/shared project LLM calls. The practical enforcement target
is:

- project code imports `llm_client` for LLM execution;
- every call is governed even when `model_policy` is omitted;
- DeepSeek V4 Flash is used by default;
- another exact allowed route includes a durable `model_justification`;
- direct raw model literals are audited;
- unlisted models are blocked regardless of override metadata.

Do not force benchmark baselines, provider SDK demos, fixture strings, or
workspace-agent SDK lanes through the same raw-model tier selector. Those still
belong under `llm_client` governance, but they need explicit exception classes
rather than pretending all model strings mean the same thing.

Use the audit in visibility mode before turning it into a CI gate:

```bash
python -m llm_client.model_policy_audit --require-llm-client path/to/project
```

For cross-workspace registration classification, use the faster registration
path:

```bash
python -m llm_client.model_policy_audit --registration-only path/to/project
```

`--registration-only` implies `--require-llm-client`, scans only production
Python files, and skips raw model-literal findings so provider-SDK migration can
be triaged separately from model-string cleanup.

`--require-llm-client` flags direct provider SDK usage such as `openai`,
`anthropic`, `litellm`, `google.genai`, LangChain provider wrappers, and similar
SDK surfaces in production Python files. It does not change the existing raw
model literal audit.

If a file must call a provider SDK directly, record an explicit exception in
that file:

```python
llm_client_registration_exception = {
    "accepted_by": "brian",
    "reason": "provider SDK documentation sample; not production execution",
    "category": "provider_sdk_demo",
}
```

Recommended exception categories:

- `benchmark_baseline` — external model baseline where using `llm_client` would
  change the benchmark surface.
- `fixture` — inert test fixture or golden sample, not executable production
  routing.
- `provider_sdk_demo` — documentation/demo code for a provider SDK.
- `llm_client_internal` — code inside `llm_client` or a sanctioned adapter layer.
- `migration_pending` — temporary production exception with a tracked migration
  issue and expiry.
