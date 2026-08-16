---
type: concept
title: Agents and Tools
description: How agent SDK routing, MCP turns, Python tools, contracts, artifacts, and evidence compose with the core runtime.
created: 2026-08-16
updated: 2026-08-16
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

# Navigation

Begin in `agent/mcp_agent.py` for the public MCP loop, then follow the turn
modules by stage. Use `agent/agent_contracts.py` for artifact and capability
requirements, `tools/tool_utils.py` for callable schemas, and
`observability/tool_calls.py` for evidence. Higher-level duet and deliberation
systems live in `workflow/`; see the [package map](../packages/package-map.md).

# Citations

1. [Agent package at the pinned revision](https://github.com/BrianMills2718/llm_client/tree/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/agent)
2. [`callable_to_openai_tool`, lines 457–538](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/tools/tool_utils.py#L457-L538)
3. [Typed tool-call observability](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/observability/tool_calls.py#L1-L161)
