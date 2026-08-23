---
type: package-map
title: Whole-Repository Package Map
description: Package-level coverage of all 165 Python modules at the current source revision.
created: 2026-08-16
updated: 2026-08-22
sources: [../sources/revision-657a98f.md, ../../../../llm_client]
confidence: high
---

# Package map

| Package | Modules | Responsibility |
| --- | ---: | --- |
| `llm_client/agent/` | 23 | MCP turn loop, planning, context budgets, tool contracts, evidence, finalization, and agent outcomes |
| Root modules | 33 | Public facade, logging, prompts, provider limits, schemas, result metadata, route certification, and compatibility surfaces |
| `workflow/` | 15 | Duet, deliberation, review-cycle, and workflow composition built on the runtime |
| `observability/` | 18 | Calls, attempts, budgets, raw artifacts, replay, comparisons, outer runs, interventions, and tool evidence |
| `core/` | 13 | Configuration, models, routing, policy, errors, availability, and typed data |
| `execution/` | 16 | Public wrappers plus text, structured, Responses, completion, stream, batch, retry, timeout, and lifecycle runtimes |
| `cli/` | 25 | Operator entrypoints for costs, traces, models, replay, reviews, route certification, and dashboards |
| `tools/` | 7 | Python/OpenAI tool schemas, registries, execution shims, and result cleaning |
| `utils/` | 9 | Cost parsing, provider coordination, rate limits, evidence spans, Git, logging, and OpenRouter helpers |
| `sdk/` | 6 | Claude and Codex agent adapters and subprocess/runtime normalization |

# How to navigate

For a public call, begin with `core/client.py`, then follow the relevant
`execution/` runtime and the shared `observability/` seams. For model-policy
changes, start in `core/`; for an agent or MCP behavior, start in `agent/` and
`tools/` but follow actual LLM calls back through the public facade. Higher-level
`workflow/` code composes these primitives and does not redefine provider
transport.

This table covers the entire current source surface at package level. The
[source-ingest page](../sources/revision-657a98f.md) records exact counts and
limits. Detailed symbol signatures and docstrings remain in older capsules;
current exact claims reopen native source rather than projecting older symbol
counts onto revision `657a98f`.

# Citations

1. [Exact source tree](https://github.com/BrianMills2718/llm_client/tree/657a98f135f6e0665cf34d81a8e8655c387dce69/llm_client)
2. [Current source coverage and provenance](../sources/revision-657a98f.md)
3. [Runtime architecture](../architecture.md)
