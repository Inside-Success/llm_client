---
type: concept
title: Agents and Tools
description: How agent SDK routing, MCP turns, Python tools, contracts, artifacts, and evidence compose with the core runtime.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/agent, ../../../../llm_client/tools, ../../../../llm_client/sdk, ../../../../llm_client/codex_canary.py, ../../../../llm_client/execution/codex_identity.py]
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

# Codex account identity evidence

`execution/codex_identity.py` (new since the former upstream revision
`4f7ecfa`) resolves which ChatGPT account a Codex call will use before dispatch.
It applies only to the model `codex` or `codex/*`. It reads `auth.json` from an
explicit `codex_home` kwarg (binding `explicit`) or from `CODEX_HOME` /
`~/.codex` (binding `ambient`), and keeps only a SHA-256 digest of
`tokens.account_id`; no path or token is retained. If the file or field is
absent (API-key authentication), the digest is `None` rather than an error, so
a caller that requires one specific account must also require an explicit
`codex_home`. The public envelope copies the binding and digest onto lifecycle
events (see [Observability and budgets](observability-and-budgets.md)).

# Dedicated Codex subscription lane

`codex_canary.py` queues jobs for one dedicated account lane under hard limits
(`CodexCanaryConfig`) and returns content-free `CodexCanaryReceipt`s.
`submit` runs a text call; `submit_structured` (added since `4f7ecfa`) takes a
Pydantic `response_model`, runs it through `acall_llm_structured` on the Codex
route, and returns a `CodexCanaryStructuredOutcome` holding the receipt plus the
typed value, which is kept out of the queue receipt. An optional explicit paid
fallback model (with a spend ceiling) is called with the same text-or-structured
shape; the typed value is returned only when the job status is `succeeded`.

# Agent submit gating

`agent/mcp_turn_outcomes.py` couples two submit gates after a pending-atoms
rejection: TODO progress and fresh evidence. A successful `todo_write` whose
status line differs from the one at the failure clears both gates, so the
submit validator re-checks the terminal even if no new evidence pointer was
added.

# Navigation

Begin in `agent/mcp_agent.py` for the public MCP loop, then follow the turn
modules by stage. Use `agent/agent_contracts.py` for artifact and capability
requirements, `tools/tool_utils.py` for callable schemas, and
`observability/tool_calls.py` for evidence. Higher-level duet and deliberation
systems live in `workflow/`; see the [package map](../packages/package-map.md).

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [Agent package](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/agent)
2. [`callable_to_openai_tool`, lines 457-538](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/tools/tool_utils.py#L457-L538)
3. [Typed tool-call observability](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/observability/tool_calls.py)
4. [Codex session contract and receipt checks, lines 731-830](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/sdk/agents_codex.py#L731-L830)
5. [Persistent-home requirement, lines 265-275](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/sdk/agents_codex.py#L265-L275)
6. [Streaming rejects explicit session modes, lines 1400-1408](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/sdk/agents_codex.py#L1400-L1408)
7. [CLI event and JSONL extraction, lines 915-916](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/sdk/agents_codex.py#L915-L916)
8. [Codex account identity, lines 1-61](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/execution/codex_identity.py#L1-L61)
9. [Canary queue, lines 105-392](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/codex_canary.py#L105-L392)
10. [Submit-gate clearing, lines 484-490](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/agent/mcp_turn_outcomes.py#L484-L490)
