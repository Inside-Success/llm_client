---
type: architecture
title: Runtime Architecture
description: The main llm_client layers and the seams through which one request becomes a governed result.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md, ../../../llm_client/core/client.py, ../../../llm_client/execution/call_wrappers.py, ../../../llm_client/execution/text_runtime.py]
confidence: high
---

# Main layers

| Layer | Responsibility | Primary package |
| --- | --- | --- |
| Public facade | Stable sync/async text, structured, tools, batch, stream, and embedding entrypoints | `llm_client/core/client.py`, re-exported by `llm_client/__init__.py` |
| Contract envelope | Required task/trace/budget metadata, budget leases, lifecycle monitor, terminal events | `llm_client/execution/call_wrappers.py` and `call_contracts.py` |
| Decision layer | Configuration, model policy, availability, normalization, route and fallback plan | `llm_client/core/` |
| Execution layer | Text, structured, Responses, completions, streaming, batch, retry, fallback, timeout | `llm_client/execution/` |
| Transport adapters | LiteLLM/provider normalization plus Claude/Codex agent SDK adapters | `llm_client/sdk/`, completion and Responses runtimes |
| Evidence layer | Calls, attempts, costs, traces, replay, raw structured artifacts, outer runs, tool calls | `llm_client/observability/` and `io_log.py` |
| Higher-level runtime | MCP agent loops, tool contracts, deliberation/review workflows, CLI surfaces | `llm_client/agent/`, `tools/`, `workflow/`, `cli/` |

# Architectural rule

The public signature stays in the facade while workload-specific control flow
lives in execution modules. For example, `call_llm` prepares a public-call
envelope and invokes `_call_llm_impl`; the sync runtime delegates to the async
implementation so the full text path has one main implementation. That runtime
resolves a call plan, validates capabilities, then executes provider attempts
through shared retry/fallback primitives. See the
[text-call lifecycle](workflows/text-call-lifecycle.md).

# Ecosystem boundary

`llm_client` is the substrate beneath application projects and evaluation
systems. It owns dispatch and evidence, while consumers own domain decisions.
The maintained boundary contract is
[`docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md` at `c2f3693`](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md).
Repository ownership is separate from runtime architecture; see
[personal/company lineage](lineage/personal-and-inside-success.md).

# Citations

1. [`call_llm` facade, lines 454–585](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/core/client.py#L454-L585)
2. [Public-call envelope and lifecycle wrapper](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/execution/call_wrappers.py#L65-L271)
3. [Text runtime implementation](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/execution/text_runtime.py#L64-L623)
