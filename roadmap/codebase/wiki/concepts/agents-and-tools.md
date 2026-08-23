---
type: concept
title: Agents and Tools
description: How agent SDK routing, MCP turns, Python tools, contracts, artifacts, and evidence compose with the core runtime.
created: 2026-08-16
updated: 2026-08-23
sources: [../../../../llm_client/agent, ../../../../llm_client/tools, ../../../../llm_client/sdk]
confidence: high
---

# Three related surfaces

1. `sdk/` adapts Claude and Codex agent execution into the common result and
   routing contracts. Agent model strings enter through the same public facade,
   while agent-only options are separated before dispatch.
2. `agent/` implements the MCP turn loop: context preparation, model stages,
   deferred tools, contract/capability checks, artifact state, evidence and
   stagnation tracking, outcomes, forced finalization, and limits.
3. `tools/` converts Python callables into tool schemas, registers and invokes
   tools, cleans results, and provides common typed outcomes.

These layers compose with—not replace—the base call runtime. Model calls still
carry task/trace/budget identity and use the routing and observability
substrate. Tool executions have their own typed result and durable logging so
an agent trace can distinguish provider work from non-LLM actions.

# Exact Codex session control

Codex's non-streaming CLI adapter supports explicit `fresh`, `resume`, and
`fork` modes. A session-aware caller supplies one dedicated, persistent Codex
home for the lineage; the adapter keeps ordinary one-shot homes temporary,
requires a returned session identity, verifies resume/fork identity semantics,
and exposes an opaque home identity in `LLMCallResult.raw_response`.

This is intentionally narrower than workflow recovery policy. The adapter owns
transport, persistence custody, and receipts; a downstream controller decides
which role may resume or fork and at what recovery tier. Streaming rejects
explicit session modes because its SDK path cannot yet meet the same receipt
contract.

# Exact Codex event custody

The direct CLI result preserves both a normalized view and the exact observed
stream. `codex_events` contains mapping-valued `item.completed` payloads;
`codex_jsonl` contains every nonblank decoded stdout line in original order,
including malformed or unknown envelopes. Consumers that need an exhaustive
experiment receipt must use and validate `codex_jsonl`, not reconstruct a
stream from the convenience projection. Both fields survive the public
structured-call path and process-safe result serialization.

# Navigation

Begin in `agent/mcp_agent.py` for the public MCP loop, then follow the turn
modules by stage. Use `agent/agent_contracts.py` for artifact and capability
requirements, `tools/tool_utils.py` for callable schemas, and
`observability/tool_calls.py` for evidence. Higher-level duet and deliberation
systems live in `workflow/`; see the [package map](../packages/package-map.md).

# Citations

1. [Agent package at the pinned revision](https://github.com/BrianMills2718/llm_client/tree/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/agent)
2. [`callable_to_openai_tool`, lines 457–538](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/tools/tool_utils.py#L457-L538)
3. [Typed tool-call observability](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/observability/tool_calls.py#L1-L161)
4. [Current exact-session and event-custody adapter](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/sdk/agents_codex.py#L590-L924)
5. [Exact-line extraction](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/sdk/agents_codex.py#L1604-L1624)
