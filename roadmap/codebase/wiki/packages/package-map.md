---
type: package-map
title: Whole-Repository Package Map
description: Package-level coverage of all 168 Python modules at the current source revision.
created: 2026-08-16
updated: 2026-10-03
sources: [../sources/revision-fe581ed.md, ../../../../llm_client]
confidence: high
---

# Package map

| Package | Modules | Responsibility |
| --- | ---: | --- |
| `llm_client/agent/` | 23 | MCP turn loop, planning, context budgets, tool contracts, evidence, finalization, and agent outcomes |
| Root modules | 34 | Public facade, logging, prompts, provider limits, schemas, result metadata, route certification, the company model-policy overlay (`inside_success_policy.py`), the Codex subscription canary queue, Langfuse callbacks, and compatibility surfaces |
| `workflow/` | 15 | Duet, deliberation, review-cycle, and workflow composition built on the runtime |
| `observability/` | 18 | Calls, attempts, budgets, raw artifacts, replay, comparisons, outer runs, interventions, and tool evidence |
| `core/` | 13 | Configuration, models, routing, policy, errors, availability, and typed data |
| `execution/` | 17 | Public wrappers plus text, structured, Responses, completion, stream, batch, retry, timeout, and lifecycle runtimes, and Codex account-identity evidence (`codex_identity.py`) |
| `cli/` | 25 | Operator entrypoints for costs, traces, models, replay, reviews, route certification, and dashboards |
| `tools/` | 7 | Python/OpenAI tool schemas, registries, execution shims, and result cleaning |
| `utils/` | 10 | Cost parsing, provider coordination, rate limits, evidence spans, Git, logging, a LiteLLM log-noise filter, and OpenRouter helpers |
| `sdk/` | 6 | Claude and Codex agent adapters and subprocess/runtime normalization |

# How to navigate

For a public call, begin with `core/client.py`, then follow the relevant
`execution/` runtime and the shared `observability/` seams. For model-policy
changes, start in `core/`; for an agent or MCP behavior, start in `agent/` and
`tools/` but follow actual LLM calls back through the public facade. Higher-level
`workflow/` code composes these primitives and does not redefine provider
transport.

This table covers the entire current source surface at package level. The
[source-ingest page](../sources/revision-fe581ed.md) records exact counts and
limits. Detailed symbol signatures and docstrings remain in older capsules;
current exact claims reopen native source rather than projecting older symbol
counts onto revision `fe581ed`.

# Citations

1. [Exact source tree](https://github.com/Inside-Success/llm_client/tree/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client)
2. [Current source coverage and provenance](../sources/revision-fe581ed.md)
3. [Runtime architecture](../architecture.md)
