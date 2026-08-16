---
type: package-map
title: Whole-Repository Package Map
description: Package-level coverage of all 155 Python modules represented by the revision-bound capsule.
created: 2026-08-16
updated: 2026-08-16
sources: [../sources/revision-c2f3693.md, ../../../../llm_client]
confidence: high
---

# Package map

| Package | Modules | Public symbols | Responsibility |
| --- | ---: | ---: | --- |
| `llm_client/agent/` | 23 | 220 | MCP turn loop, planning, context budgets, tool contracts, evidence, finalization, and agent outcomes |
| Root modules | 27 | 189 | Public facade, logging, prompts, provider limits, schemas, result metadata, route certification, and compatibility surfaces |
| `workflow/` | 15 | 161 | Duet, deliberation, review-cycle, and workflow composition built on the runtime |
| `observability/` | 17 | 153 | Calls, attempts, budgets, raw artifacts, replay, comparisons, outer runs, interventions, and tool evidence |
| `core/` | 13 | 118 | Configuration, models, routing, policy, errors, availability, and typed data |
| `execution/` | 16 | 78 | Public wrappers plus text, structured, Responses, completion, stream, batch, retry, timeout, and lifecycle runtimes |
| `cli/` | 23 | 62 | Operator entrypoints for costs, traces, models, replay, reviews, route certification, and dashboards |
| `tools/` | 7 | 43 | Python/OpenAI tool schemas, registries, execution shims, and result cleaning |
| `utils/` | 8 | 40 | Cost parsing, provider coordination, rate limits, evidence spans, Git, logging, and OpenRouter helpers |
| `sdk/` | 6 | 15 | Claude and Codex agent adapters and subprocess/runtime normalization |

# How to navigate

For a public call, begin with `core/client.py`, then follow the relevant
`execution/` runtime and the shared `observability/` seams. For model-policy
changes, start in `core/`; for an agent or MCP behavior, start in `agent/` and
`tools/` but follow actual LLM calls back through the public facade. Higher-level
`workflow/` code composes these primitives and does not redefine provider
transport.

This table covers the entire source capsule at package level. The
[source-ingest page](../sources/revision-c2f3693.md) records exact counts and
limits; detailed symbol signatures and docstrings remain in the capsule rather
than being duplicated into 1,079 Markdown entries.

# Citations

1. [Exact source tree](https://github.com/BrianMills2718/llm_client/tree/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client)
2. [Capsule coverage and provenance](../sources/revision-c2f3693.md)
3. [Runtime architecture](../architecture.md)
