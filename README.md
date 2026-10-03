# llm-client

Unified LLM client with mandatory observability, cost tracking, and policy
enforcement. Built on [LiteLLM](https://github.com/BerriAI/litellm) for
multi-provider transport.

**Why this exists:** every LLM call across every project gets logged with cost,
tokens, latency, and trace context — automatically. No call escapes without
declaring what it's for (`task`), where it fits (`trace_id`), and how much it
can spend (`max_budget`).

Repo-local ownership and boundary posture now live in
[docs/ops/CAPABILITY_DECOMPOSITION.md](docs/ops/CAPABILITY_DECOMPOSITION.md).
Use that doc when you need the current source of record for what `llm_client`
owns versus what it intentionally consumes from `prompt_eval`, `project-meta`,
or project repos.

## Governed workflow

`llm_client` now exposes sanctioned worktree coordination through its Makefile:

```bash
make worktree BRANCH=plan-22-example TASK="Describe the task" PLAN=22
make worktree-list
make worktree-remove BRANCH=plan-22-example
```

Prefer these entrypoints over ad hoc local worktree commands for bounded
implementation work. `make help` lists the full session/claim target set; the
command reference is `scripts/AGENTS.md`.

## Agent collaboration workflows

The Claude/Codex collaboration commands replace manual
paste-between-terminal loops with structured `llm_client` calls and on-disk
artifacts:

- `python -m llm_client duet-review --help` reviews an existing plan and,
  optionally, the implementation diff against that plan.
- `python -m llm_client review-artifact --help` performs a standalone
  adversarial review of a patch, plan, decision, or text artifact. It is
  designed to run in the background while the foreground agent keeps working.
- `python -m llm_client deliberate-task --help` runs a two-agent symmetric
  debate, usually `codex/gpt-5.6-luna` plus `claude-code/sonnet`, with persisted
  positions and synthesis.

See [docs/guides/agent-collaboration.md](docs/guides/agent-collaboration.md)
for install notes, command examples, and the tracked dogfood evidence map.

## Install

```bash
git clone https://github.com/Inside-Success/llm_client && cd llm_client
pip install -e .          # instructor (Pydantic extraction) is a core dependency
pip install -e ".[dev]"  # + pytest, mypy, ruff, vulture, langgraph (make install does this)
```

## Quick start

```python
from llm_client import WorkloadRouteContext, call_llm, resolve_workload_route

route = resolve_workload_route(
    WorkloadRouteContext(
        codex_compatible=True,
        environment="trusted_private_automation",
        subscription_auth_supported=True,
        subscription_capacity="available",
        requires_openai_api_contract=False,
        requires_openrouter_features=False,
        openrouter_is_live_best_value=False,
    )
)

result = call_llm(
    route.model,
    [{"role": "user", "content": "Summarize this note"}],
    reasoning_effort=route.reasoning_effort,
    model_policy="enforce_allowlist",
    model_justification=route.model_justification,
    task="extraction",
    trace_id="demo/basic",
    max_budget=1.00,
)
print(result.content)
print(f"${result.cost:.4f} | {result.usage['total_tokens']} tokens")
```

### Structured output

```python
from pydantic import BaseModel
from llm_client import call_llm_structured

class Sentiment(BaseModel):
    label: str
    score: float

sentiment, meta = call_llm_structured(
    "openrouter/deepseek/deepseek-v4-flash",
    [{"role": "user", "content": "I love this product!"}],
    response_model=Sentiment,
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    task="sentiment",
    trace_id="demo/sentiment",
    max_budget=1.00,
)
print(sentiment.label, sentiment.score, f"${meta.cost:.4f}")
```

Callers that own JSON Schema outside Python can use `call_llm_json_schema` or
the versioned local bridge:

```bash
python -m llm_client json-schema-call --request request.json
```

The request requires a model, messages, `responseSchema`, `task`, `traceId`,
and `maxBudget`. Credentials and provider endpoints are intentionally absent.
Results are validated against the original schema even when a provider needs
a narrower projected schema.

### Async

```python
from llm_client import acall_llm, acall_llm_structured, acall_llm_batch

result = await acall_llm("openrouter/deepseek/deepseek-v4-flash", messages,
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    task="async_demo", trace_id="demo/async", max_budget=1.00)

# Concurrent batch
results = await acall_llm_batch("openrouter/deepseek/deepseek-v4-flash", [msgs1, msgs2, msgs3],
    reasoning_effort="none",
    model_policy="enforce_allowlist",
    max_concurrent=5, task="batch_demo", trace_id="demo/batch", max_budget=2.00)
```

## Core API

Sixteen functions (8 sync + 8 async):

| Function | Async | Returns | Purpose |
|----------|-------|---------|---------|
| `call_llm` | `acall_llm` | `LLMCallResult` | Text completion |
| `call_llm_structured` | `acall_llm_structured` | `(T, LLMCallResult)` | Pydantic extraction |
| `call_llm_with_tools` | `acall_llm_with_tools` | `LLMCallResult` | Tool/function calling |
| `call_llm_batch` | `acall_llm_batch` | `list[LLMCallResult]` | Concurrent batch |
| `call_llm_structured_batch` | `acall_llm_structured_batch` | `list[(T, LLMCallResult)]` | Structured batch |
| `stream_llm` | `astream_llm` | `LLMStream` | Streaming |
| `stream_llm_with_tools` | `astream_llm_with_tools` | `LLMStream` | Streaming + tools |
| `embed` | `aembed` | `EmbeddingResult` | Embeddings |

**Required on every call:** `task=`, `trace_id=`, `max_budget=`

Reasoning-configurable models also require an explicit `reasoning_effort=`.
Use `"none"` only for routes whose reviewed capability supports turning
reasoning off; omitted effort never delegates the choice to the provider.

**Result fields:** `.content`, `.usage`, `.cost`, `.marginal_cost`, `.model`,
`.tool_calls`, `.finish_reason`, `.routing_trace`, `.cache_hit`

## Model selection

Prefer task-based selection over hardcoded model IDs:

```python
from llm_client import get_model, list_models

model = get_model("default_intelligent")       # Shared default for ordinary project work
models = list_models("default_intelligent")    # All candidates, ranked
```

Current task profiles: `default_intelligent`, `fast_intelligent`, `fast_mid`,
`fast_cheap_mid`, `ultra_cheap_low_intel`, `ultra_fast_low_intel`,
`very_intelligent`, `max_intelligence`. Older names (`extraction`,
`budget_extraction`, `graph_building`, `fast_extraction`, `bulk_cheap`,
`synthesis`, `deep_review`, `code_generation`, `judging`, `agent_reasoning`)
remain as compatibility selectors that point at the profiles above. Run
`python -m llm_client models tasks` (or `list_models(task)`) for the live list
and candidates per task.

## Observability

Every call is logged to JSONL + SQLite automatically.

### Cost CLI

```bash
python -m llm_client cost                          # total spend
python -m llm_client cost --group-by project       # spend per project
python -m llm_client cost --group-by model --days 7  # spend per model, last week
python -m llm_client cost --project myproject --format json
```

### Query from code

```python
from llm_client import get_cost, get_runs

cost = get_cost(project="myproject", days=7)
runs = get_runs(project="myproject")
```

### Traces

```bash
python -m llm_client traces --limit 20            # recent traces with cost rollup
python -m llm_client traces --trace-id demo/basic  # one trace across llm_calls and tool_calls
```

## Configuration

### API keys

```bash
export OPENROUTER_API_KEY=sk-or-...    # Default for most models
export GEMINI_API_KEY=...              # Direct Gemini models
export ANTHROPIC_API_KEY=sk-ant-...    # Direct Anthropic
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_CLIENT_OPENROUTER_ROUTING` | `on` | Route through OpenRouter by default |
| `LLM_CLIENT_DATA_ROOT` | `~/projects/data` | Observability data directory |
| `LLM_CLIENT_PROJECT` | `basename(cwd)` | Project name for logging |
| `LLM_CLIENT_REQUIRE_TAGS` | off | Strict enforcement of task/trace_id/max_budget (also on when `CI` is truthy or the task starts with `benchmark`/`bench`/`eval`/`ci`) |
| `LLM_CLIENT_TIMEOUT_POLICY` | `allow` | `ban` to disable all per-call timeouts |
| `LLM_CLIENT_DB_PATH` | `$LLM_CLIENT_DATA_ROOT/llm_observability.db` | SQLite observability DB path |
| `LLM_CLIENT_LOG_ENABLED` | `1` | Disable logging with `0` |
| `LLM_CLIENT_RATE_LIMIT_SHARED_ENABLED` | `1` | Enable cross-process shared provider leases |
| `LLM_CLIENT_RATE_LIMIT_SHARED_LIMITS` | provider defaults | Override cross-process provider caps as JSON |
| `LLM_CLIENT_RATE_LIMIT_COOLDOWN_FLOORS` | provider defaults | Override provider cooldown floors as JSON |
| `LLM_CLIENT_RATE_LIMIT_STATE_PATH` | `~/projects/data/llm_rate_limit_state.sqlite3` | Shared SQLite state for cooldowns and leases |

### Provider governance

- GPT-5.4-family requests are hard-blocked before dispatch; use GPT-5.6 Luna where the execution contract permits it.
- Bare Gemini ids canonicalize to `gemini/<model>` before provider selection.
- Gemini shared-cap and cooldown defaults come from the typed provider-governance policy, not scattered literals.
- `result.routing_trace["provider_governance_events"]` records canonicalization decisions for click-through debugging and downstream operator tooling.

### Tool-call observability

Non-LLM tool calls (retrieval, fetch, extraction) can be logged alongside LLM calls:

```python
from llm_client import log_tool_call

log_tool_call(
    tool_name="search_entities",
    operation="retrieval",
    result_count=15,
    task="graph_building",
    trace_id="demo/tools",
)
```

```bash
python -m llm_client tools --group-by tool_name --days 7
```

### Rubric scoring

```python
from llm_client import load_categorical_rubric

rubric = load_categorical_rubric("extraction_quality")
score = rubric.score_categorical({"completeness": "complete", "accuracy": "mostly_accurate"})
```

### Log maintenance

```bash
python scripts/log_maintenance.py stats             # Show log sizes and date ranges
python scripts/log_maintenance.py rotate --max-size 100   # Rotate logs larger than 100 MB
python scripts/log_maintenance.py cleanup --days 90       # Archive logs older than 90 days (--delete-days N also deletes old archives)
# add --dry-run (-n) to preview
```

## Using from another project

Install as above (`pip install -e <path-to-clone>`), then `from llm_client import call_llm`.

## Detailed guides

- [Advanced usage](docs/guides/advanced-usage.md) — retry policies, fallback models, caching, streaming, hooks, routing config
- [MCP agent contracts](docs/guides/mcp-agent-contracts.md) — tool-chain enforcement, progressive disclosure, artifact handles
- [Codex integration](docs/guides/codex-integration.md) — process isolation, transport fallback, billing modes
- [Experiment observability](docs/guides/experiment-observability.md) — runs, items, CLI, adoption gates
- [Capability decomposition](docs/ops/CAPABILITY_DECOMPOSITION.md) — repo-local ownership and boundary source of record
- [API reference](docs/API_REFERENCE.md) — full generated reference
- [Architecture decisions](docs/adr/) — ADRs for routing, identity, observability boundaries

## Repository navigation

The concern front doors route without relocating existing authorities:
[`docs/`](docs/), [`roadmap/`](roadmap/), [`src/`](src/), [`tests/`](tests/),
[`ui/`](ui/), [`generated/`](generated/), and [`misc/`](misc/).

[Wiki routing stub](wiki/index.md)
