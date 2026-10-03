# Advanced Usage

## Long-thinking mode

`gpt-5.2-pro` and `gpt-5.5-pro` (`_LONG_THINKING_MODELS` in
`llm_client/execution/background_runtime.py`) support long-thinking runs. Set `reasoning_effort="high"` or
`"xhigh"` to enable Responses background mode with automatic polling:

```python
result = call_llm(
    "gpt-5.2-pro",
    messages,
    reasoning_effort="xhigh",
    task="long_thinking",
    trace_id="long_thinking",
    max_budget=5.00,
    background_timeout=900,
    background_poll_interval=15,
)
```

Requires `OPENROUTER_API_KEY` (OpenRouter endpoint) or `OPENAI_API_KEY` (direct).

Note: neither long-thinking model is in the current `call_llm` execution
allowlist (`ALLOWED_EXECUTION_MODELS` in
`llm_client/core/model_execution_policy.py`), so the call above raises
`LLMConfigurationError` ("model is not in the llm_client execution allowlist")
today. The background runtime exists, but using it requires adding a reviewed
allowlist entry first.

## Model policy

Every `call_llm` call is checked against an allowlist (`model_policy`
accepts only `"enforce_allowlist"`, which is also the default). Any allowed
model other than the default (`openrouter/openai/gpt-5.6-luna`) requires a
non-empty `model_justification=`, and configurable-reasoning models require an
explicit `reasoning_effort=` (use `"none"` for off). The examples below follow
this contract. Details: `llm_client/core/model_execution_policy.py`;
route selection: [model-selection.md](model-selection.md).

## Execution modes

`execution_mode` enforces model capabilities before dispatch:

- `text` (default): regular completion calls.
- `structured`: structured extraction intent.
- `workspace_agent`: requires agent models (`codex`, `claude-code`, `openai-agents/*`).
- `workspace_tools`: requires non-agent models with `python_tools`, `mcp_servers`, or `mcp_sessions`.

## Retry policy

```python
from llm_client import RetryPolicy, call_llm, linear_backoff

policy = RetryPolicy(
    max_retries=5,
    base_delay=0.5,
    backoff=linear_backoff,
    retry_on=["custom error"],
    on_retry=lambda a, err, d: print(f"Retry {a}"),
)
result = call_llm(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    reasoning_effort="none",
    retry=policy,
    model_policy="enforce_allowlist",
    model_justification="Cheap bulk route reviewed for this task.",
    task="...",
    trace_id="...",
    max_budget=1.00,
)
```

## Fallback models

```python
result = call_llm(
    "openrouter/deepseek/deepseek-v4-flash", messages,
    fallback_models=["gemini/gemini-2.5-flash"],
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    model_justification="Retain the reviewed Gemini route for provider continuity.",
    task="fallbacks",
    trace_id="fallbacks",
    max_budget=1.00,
    on_fallback=lambda failed, err, next_: print(f"{failed} failed, trying {next_}"),
)
```

## Observability hooks

```python
from llm_client import Hooks, call_llm

hooks = Hooks(
    before_call=lambda model, msgs, kw: print(f"Calling {model}"),
    after_call=lambda result: print(f"${result.cost:.4f}"),
    on_error=lambda err, attempt: print(f"Attempt {attempt} failed"),
)
result = call_llm(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    hooks=hooks,
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    model_justification="Cheap bulk route reviewed for this task.",
    task="...",
    trace_id="...",
    max_budget=1.00,
)
```

## Response caching

```python
from llm_client import LRUCache, call_llm

cache = LRUCache(maxsize=128, ttl=3600)
result = call_llm(
    "openrouter/deepseek/deepseek-v4-flash",
    messages,
    cache=cache,
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    model_justification="Cheap bulk route reviewed for this task.",
    task="...",
    trace_id="...",
    max_budget=1.00,
)
# Second call with same args returns cached (cache_hit=True, marginal_cost=0.0)
```

Implement `CachePolicy` protocol for custom backends (Redis, disk, etc.).

## Routing configuration

OpenRouter-first routing is on by default. To use direct provider routing:

```python
from llm_client import ClientConfig, call_llm

cfg = ClientConfig(routing_policy="direct")
result = call_llm(
    "gpt-5.6-terra",
    messages,
    config=cfg,
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    model_justification="Use the certified direct Terra route for this task.",
    task="...",
    trace_id="...",
    max_budget=1.00,
)
```

Or via environment: `LLM_CLIENT_OPENROUTER_ROUTING=off`

Provider-governance rules are applied before the final routing decision:

- GPT-5.4-family exact aliases are flagged as prohibited (use GPT-5.6 Luna when compatible);
  bare `gpt-5.4*` ids fail before dispatch, but the Inside Success overlay routes in
  `llm_client/inside_success_policy.py` (for example `openrouter/openai/gpt-5.4-mini`)
  are allowlisted and still reach dispatch with a logged governance warning
- bare Gemini ids canonicalize to `gemini/<model>`
- `result.routing_trace["provider_governance_events"]` records these decisions

### Shared provider coordination

Gemini and other providers can use shared cooldown and lease state across
processes/worktrees to prevent first-attempt stampedes against the same quota
surface.

- `LLM_CLIENT_RATE_LIMIT_SHARED_ENABLED=1` enables shared leases
- `LLM_CLIENT_RATE_LIMIT_SHARED_LIMITS='{"google": 4}'` overrides provider caps
- `LLM_CLIENT_RATE_LIMIT_COOLDOWN_FLOORS='{"google": 15}'` overrides provider cooldown floors
- `LLM_CLIENT_RATE_LIMIT_STATE_PATH=/path/to/llm_rate_limit_state.sqlite3` changes the SQLite state location

### OpenRouter key rotation

If OpenRouter returns key exhaustion (402/403), retry loops auto-rotate to backup keys.
Configure a key pool with:
- `OPENROUTER_API_KEYS` (comma/semicolon/newline-delimited), or
- `OPENROUTER_API_KEY` plus numbered vars (`OPENROUTER_API_KEY_2`, `_3`, ...).

The key ring never crosses billing accounts: keys that belong to a different
account than the one owning the repository's spend are dropped, not failed over
to (`_apply_account_routing` in `llm_client/utils/openrouter.py`; per-repository
account map in `llm_client/data/openrouter_account_routing.json`).

## Timeout policy

- `LLM_CLIENT_TIMEOUT_POLICY=ban` — disable all per-call request timeouts globally
  (also accepted: `disable`, `disabled`, `off`, `none`, `false`, `no`, `0`).
- `LLM_CLIENT_TIMEOUT_POLICY=allow` (default) — permit explicit `timeout` values
  (see `llm_client/execution/timeout_policy.py`).

## Foundation event strict mode

MCP/tool loops validate emitted foundation events. Enable strict failure mode:

```bash
export FOUNDATION_SCHEMA_STRICT=1
```

## Inspect active calls

```python
from llm_client import get_active_llm_calls
active = get_active_llm_calls(project="my-project", limit=20)
```

## Model identity fields

- `result.model` — legacy compatibility; use `resolved_model` instead
- `result.cost` — cost of the call; `result.marginal_cost` — cost attributable to this call (0.0 on a cache hit)
- `result.requested_model` — caller input
- `result.resolved_model` / `result.execution_model` — terminal executed model
- `result.routing_trace` — routing/fallback metadata
- `result.warning_records` — machine-readable `LLMC_WARN_*` warnings
