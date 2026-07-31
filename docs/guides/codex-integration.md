# Codex Integration

## Workspace agent mode

For code-generation/editing workflows that depend on workspace side effects,
set `execution_mode="workspace_agent"` to prevent accidental routing to
chat-only models.

```python
result = call_llm(
    "codex/gpt-5",
    messages,
    execution_mode="workspace_agent",
    task="codex_demo",
    trace_id="codex_demo",
    max_budget=5.00,
)
```

Default agent settings:
- `codex`: `approval_policy="never"`, `skip_git_repo_check=True`
- `claude-code`: `permission_mode="bypassPermissions"`

For fully headless agent runs, `yolo_mode=True` is a convenience flag.

## Process isolation (hang containment)

For `codex` calls that occasionally become cancellation-unresponsive under long
tool loops, run non-streaming turns in a dedicated worker process:

```python
result = call_llm(
    "codex/gpt-5",
    messages,
    execution_mode="workspace_agent",
    task="codex_isolation",
    trace_id="codex_isolation",
    max_budget=5.00,
    codex_process_isolation=True,
    codex_process_start_method="fork",   # optional
    codex_process_grace_s=3.0,           # optional
)
```

Or via environment:

```bash
export LLM_CLIENT_CODEX_PROCESS_ISOLATION=1
export LLM_CLIENT_CODEX_PROCESS_START_METHOD=fork
export LLM_CLIENT_CODEX_PROCESS_GRACE_S=3.0
```

## Transport fallback

Three transport modes:
- `codex_transport="sdk"`: SDK only.
- `codex_transport="cli"`: `codex exec` directly.
- `codex_transport="auto"`: prefer SDK, fall back to CLI on failure.

If timeouts are globally disabled (`LLM_CLIENT_TIMEOUT_POLICY=ban`), pair
auto transport with `agent_hard_timeout`:

```python
result = call_llm(
    "codex",
    messages,
    execution_mode="workspace_agent",
    task="codex_transport",
    trace_id="codex_transport",
    max_budget=5.00,
    codex_transport="auto",
    agent_hard_timeout=300,
    reasoning_effort="medium",
)
```

## Reasoning effort

- Codex calls require explicit public `reasoning_effort="low"`, `"medium"`,
  or `"high"`.
- Omission and unsupported values fail before agent dispatch. The client does
  not default or coerce the requested effort.
- `model_reasoning_effort` is an adapter transport detail; ordinary callers
  should use the public `reasoning_effort` control.
- ChatGPT-authenticated callers may explicitly select
  `codex/gpt-5.6-luna`. It is allowlisted for low, medium, and high effort but
  is not a shared task-tier default. Use `codex_transport="cli"` when the
  installed Python environment does not include the optional Codex SDK.
- `codex/gpt-5.6-terra` is a separately selected subscription route with
  explicit low, medium, and high reasoning. It does not replace Luna or create
  a fallback chain.
- `codex/gpt-5.6-sol` is also an explicit subscription route with low, medium,
  and high reasoning; callers still provide a non-default-model justification.

## Agent billing and retry

- Default billing: `LLM_CLIENT_AGENT_BILLING_MODE=subscription` (cost=0.0, billing_mode="subscription_included")
- API-metered: `LLM_CLIENT_AGENT_BILLING_MODE=api`
- Retries disabled by default (avoid duplicate side effects). Enable with `agent_retry_safe=True` or `LLM_CLIENT_AGENT_RETRY_SAFE=1`.
