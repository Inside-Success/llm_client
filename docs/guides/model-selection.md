# Model Selection

`llm_client` model selection has two separate decisions:

1. **Raw model tier** — speed/cost/intelligence tradeoff for ordinary text or
   structured-output calls.
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
| `very_intelligent` | Grok 4.5 | difficult reasoning before max-cost escalation | automatic bulk pipelines |
| `max_intelligence` | Claude Opus 4.8 | explicit max-quality escalation | default routing |

Compatibility selectors such as `extraction`, `judging`, `synthesis`, and
`bulk_cheap` remain available so existing projects do not break. New code
should use the tier names above and keep task intent in the required
`task=` observability tag.

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
