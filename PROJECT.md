# LLM Client Project Dossier

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Portfolio Role

`llm_client` is supporting shared infrastructure. It is the Brian-built runtime
and observability substrate for LLM, embedding, structured-output, streaming,
batch, and tool-call work across the project ecosystem.

It should not lead the portfolio as a standalone analyst artifact. Its value is
that applied projects can show exactly what model was called, why it was
called, what it cost, how long it took, whether it passed the structured-output
contract, and how the call fits into a larger trace.

## Current Status

Safe current claims:

- core sync and async LLM call surfaces exist for text, structured output,
  tools, streaming, batch execution, and embeddings;
- every call can carry required `task`, `trace_id`, and `max_budget` metadata;
- results include content, usage, cost, marginal cost, model, finish reason,
  routing trace, tool calls, and cache status;
- JSONL and SQLite observability capture cost, latency, tokens, errors, and
  trace context;
- task-based model selection exists through the model registry;
- structured output uses Pydantic-facing contracts and provider schema support;
- non-LLM tool calls can be logged alongside LLM calls;
- API reference, requirements, ADRs, and an applied observability portfolio
  case exist.

Do not claim:

- this repo is an analyst product;
- API breadth by itself is portfolio evidence;
- it owns prompt-evaluation semantics or optimization loops;
- it owns project-specific retrieval, qualitative coding, or OSINT logic;
- it is a general workflow engine or agent framework;
- observability proves a downstream claim without applied project evidence.

## Reviewer Path

1. Read [README.md](README.md) for the public runtime surface.
2. Read [docs/APPLIED_OBSERVABILITY_CASE.md](docs/APPLIED_OBSERVABILITY_CASE.md)
   for the portfolio framing: infrastructure matters when a trace changes an
   engineering decision.
3. Read [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for scope and non-goals.
4. Read [docs/ops/CAPABILITY_DECOMPOSITION.md](docs/ops/CAPABILITY_DECOMPOSITION.md)
   for ownership boundaries.
5. Read [docs/adr/0010-cross-project-runtime-substrate.md](docs/adr/0010-cross-project-runtime-substrate.md)
   and [docs/adr/0007-observability-contract-boundary.md](docs/adr/0007-observability-contract-boundary.md)
   for the runtime and observability decisions.
6. Read [docs/VALIDATION.md](docs/VALIDATION.md) and
   [docs/CONCERNS.md](docs/CONCERNS.md) before using this as portfolio
   evidence.

## Why It Matters For An AI Engineer / Analyst Portfolio

Applied LLM systems are hard to trust when model calls are invisible,
unbudgeted, and untraceable. This repo shows the infrastructure layer that
makes those systems governable: structured outputs, budget metadata, trace
context, cost accounting, error reporting, model policy, and replay-oriented
observability.

The best public framing is: "I built the shared LLM runtime and observability
layer so applied research systems can inspect, budget, debug, and govern every
model and tool call."

## Next Evidence To Create

The strongest portfolio artifact is an applied trace from a downstream project:

1. Pick a real downstream decision, such as rerouting a task, fixing a schema,
   changing a retry policy, or removing an expensive step.
2. Show the cost/error/latency/validation trace that exposed the issue.
3. Show the engineering change made because of that trace.
4. Show the downstream result improved or became easier to diagnose.
