# llm-client

llm-client is a general-purpose runtime for calling LLM providers with
consistent routing, structured output, budgets, retries, and observability. It
uses [LiteLLM](https://github.com/BerriAI/litellm) for multi-provider transport.

Every call records cost, tokens, latency, task, and trace context. Public calls
require task, trace_id, and max_budget so operational intent and spend remain
inspectable.

## What It Owns

- provider-neutral text, structured-output, tool-calling, streaming, batch, and
  embedding APIs;
- task-based model selection and routing policy;
- retry, rate-limit, and budget enforcement;
- prompt-asset loading;
- run, item, token, latency, error, and cost observability;
- optional agent SDK and MCP integrations.

It does not own a product's data sources, domain schema, business rules,
evaluation semantics, or user interface.

## Inside Success Use

Inside Success uses llm-client beneath ontology extraction, graph retrieval, and
evaluation. The product and platform repositories supply their own prompts,
contracts, source access, and acceptance criteria. This library supplies the
shared execution and observability mechanism and remains reusable outside
Inside Success.

## Install

```bash
pip install -e .
pip install -e ".[structured]"
```

## Quick Start

```python
from llm_client import call_llm, get_model

result = call_llm(
    get_model("extraction"),
    [{"role": "user", "content": "Summarize this note."}],
    task="extraction",
    trace_id="example/summarize",
    max_budget=1.00,
)

print(result.content)
print(result.cost)
```

Structured output uses Pydantic models through call_llm_structured. Async,
streaming, tool-calling, batch, and embedding variants are exposed from the
same package.

## Operations

```bash
make help
make test-quick
make check
make cost-by-task
make errors
```

## Documentation

- [Capability boundaries](docs/ops/CAPABILITY_DECOMPOSITION.md)
- [API reference](docs/API_REFERENCE.md)
- [Model registry](docs/MODEL_REGISTRY.md)
- [Agent collaboration](docs/guides/agent-collaboration.md)
- [Architecture decisions](docs/adr/README.md)
- [Plan index](docs/plans/CLAUDE.md)

The API reference is generated from the public surface. Regenerate it after
changing public functions or docstrings.
