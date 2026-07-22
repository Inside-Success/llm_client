# Model Selection

`llm_client` model selection has two separate decisions:

1. **Raw model tier** — task-shape, latency, and reasoning tradeoff for ordinary
   text or structured-output calls. Cost is observed, not a launch gate.
2. **Execution mode** — whether the call needs a workspace-agent SDK lane with
   side effects, tools, and repository context.

Do not use agent SDK models merely because they are “smarter.” Use them when
the workflow needs workspace side effects:

```python
result = call_llm(
    "codex/gpt-5.4",
    messages,
    execution_mode="workspace_agent",
    task="repo_edit",
    trace_id=trace_id,
    max_budget=5.00,
)
```

For ordinary model selection, prefer tier selectors:

| Selector | Default model | Use for | Do not use for |
|---|---|---|---|
| `ultra_fast_low_intel` | Mercury 2 | tiny rewrites, routing, low-stakes transforms | judgment, synthesis, policy |
| `ultra_cheap_low_intel` | GPT-5 nano | disposable low-stakes bulk work | correctness-sensitive work |
| `fast_cheap_mid` | DeepSeek V4 Flash | bulk structured work with a real reasoning floor | final review or high-stakes decisions |
| `fast_mid` | GPT-5.4 nano | latency-sensitive general work | deep reasoning |
| `default_intelligent` | MiniMax-M3 | normal project default | workspace side effects |
| `fast_intelligent` | GLM 5.2 | stronger reasoning without huge latency | final “best possible” escalation |
| `very_intelligent` | Grok 4.5 | difficult semantic judgment, coreference, ontology authoring, and deep review | automatic bulk pipelines |
| `max_intelligence` | Claude Opus 4.8 | explicit max-quality escalation | default routing |

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

## Declared Capability vs. Certified Route

`structured_output: true` in the model registry means the route is **declared**
as intended to support native JSON-schema output. It is not proof that the
current provider route accepts this repository's strict schema at runtime.

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
| `openrouter/openai/gpt-5.5` | historical proxy route | **Rejected before dispatch by local capability map** | The former Plan 106 result was an OpenRouter-proxy result, not a direct OpenAI result. It is not evidence about direct GPT-5.5 or later GPT-5.6 models. |
| direct `gpt-5.5` | historical only | **Certified for one bounded strict-schema contract** | Direct OpenAI Responses API returned parseable typed content when routing was explicit. This corrects Plan 106's false direct-route disposition, but GPT-5.5 is superseded for new selection by the GPT-5.6 family. Evidence: `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md`. |
| direct `gpt-5.6` (Sol) | explicit manual selection | **Certified for one bounded strict-schema contract** | Direct OpenAI Responses API returned schema-valid typed content. The provider-policy exact alias preserves this direct route even while normal routing prefers OpenRouter. It is not yet an automatic tier default or semantic-quality certification. Evidence: `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md`. |
| direct `gpt-5.6-terra` | explicit manual selection | **Certified for one bounded strict-schema contract** | Same contract-tested direct Responses API route as Sol, retained as an explicit choice rather than a default. Evidence: `docs/runs/2026-07-16_gpt5_direct_native_schema_route_certification.md`. |
| GPT-5.6 Luna | none yet | **Official capability, locally unregistered and uncertified** | [OpenAI documents](https://developers.openai.com/api/docs/models) native structured-output support, but this exact route has no retained `llm_client` passing trace. Do not select it until registered and certified. |

When a route changes status, update this table together with the retained run
record. A route may move from declared to certified only after a real call
returns parseable content under the named contract. A failed call must record
whether failure occurred before provider dispatch, at schema transport, at
provider capacity/quota, or during local contract validation; never label all
of these simply “model failure.”

Provider documentation is useful for deciding which route to register and
probe, but it does not certify a local route. GPT-5.6 Sol and Terra now have
bounded direct-route evidence; Luna remains a provider-declared capability,
not a `llm_client` selection default or an observed result.

Fable-family models are banned. They must not appear in the registry, project
config, direct `call_llm(...)` calls, or override fields. Generic
`model_override_acceptance` does not authorize Fable.

## Should every project register through `llm_client`?

Yes for production/shared project LLM calls. The practical enforcement target
is:

- project code imports `llm_client` for LLM execution;
- model choice uses a tier selector or a documented override;
- direct raw model literals are audited;
- banned models are blocked regardless of override metadata.

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
