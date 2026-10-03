---
type: source
title: Inside Success Revision fe581ed Source Ingest
description: Current source binding to canonical Inside-Success/llm_client main, with the concept and workflow pages re-derived from code since the former personal revision 4f7ecfa.
created: 2026-10-03
updated: 2026-10-03
sources: [../../raw/source-manifest-fe581ed-inside-success.json, ../../../../llm_client/inside_success_policy.py, ../../../../llm_client/execution/codex_identity.py, ../../../../llm_client/utils/litellm_log_filters.py]
confidence: high
---

# Current source binding

The source is `Inside-Success/llm_client` commit
`fe581ed19486f26dd06e8d08366ebe2bda21f8d1`, Git tree
`1accdb4ccbe20c09380eb307ed3f5d22e66df547`. Its code surface is unchanged from
[`5228ceb`](revision-5228ceb.md): 168 Python files plus `pyproject.toml` (169
files), digest `sha256:a29cd7f0...a662da`. The immutable
[manifest](../../raw/source-manifest-fe581ed-inside-success.json) carries the same authority hashes as
[`98c9333`](../../raw/source-manifest-98c9333-inside-success.json); it is the
manifest `make codebase-wiki-check` reads.

# What this ingest re-derived

`git diff 4f7ecfa..fe581ed -- llm_client pyproject.toml` shows three new Python
modules, edits to 15 existing modules, and `CLAUDE.md` to `AGENTS.md` renames in
package directories. Every statement on the pages below was re-read from code at
this revision, and every citation was repointed to
`Inside-Success/llm_client@fe581ed` with line ranges checked against that tree.

| Page | What changed |
| --- | --- |
| [Model selection and routing](../concepts/model-selection-and-routing.md) | Company allowlist overlay (`inside_success_policy.py`), retry classification for provider failures, compact retry-log summaries |
| [Structured output](../concepts/structured-output.md) | Provider-reported `finish_reason=error` check, timeout default under the timeout ban |
| [Observability and budgets](../concepts/observability-and-budgets.md) | Codex account evidence on lifecycle events, Langfuse content policy, LiteLLM log filter |
| [Agents and tools](../concepts/agents-and-tools.md) | Codex account identity, canary `submit_structured`, submit-gate clearing |
| [Public API and contracts](../concepts/public-api-and-contracts.md) | Prompt-size ceiling and identity step in the call envelope; timeout policy |
| [Prompt assets](../concepts/prompt-assets.md) | Prompt context-contract and duplicate-content checks (already in code, previously undocumented) |
| [Text-call](../workflows/text-call-lifecycle.md) and [structured-call](../workflows/structured-call-lifecycle.md) lifecycles | Envelope steps and provider-failure handling |

Modules new since `4f7ecfa`: `llm_client/inside_success_policy.py`,
`llm_client/execution/codex_identity.py`, `llm_client/utils/litellm_log_filters.py`.
Modified: `agent/mcp_turn_outcomes.py`, `codex_canary.py`, `core/client.py`,
`core/errors.py`, `core/model_execution_policy.py`, `execution/call_contracts.py`,
`call_lifecycle.py`, `call_wrappers.py`, `execution_kernel.py`, `retry.py`,
`structured_runtime.py`, `timeout_policy.py`, `langfuse_callbacks.py`,
`utils/openrouter.py`.

# Limits

The [architecture](../architecture.md), [overview](../overview.md), and
[package map](../packages/package-map.md) were checked for contradictions with
these edits (package counts re-counted: 168 files); only the package map needed
changes. No repository capsule exists for this revision. The manifest's network
pin records `fe581ed` as the observed `main` head at ingest time and goes stale
when `main` moves, as expected for `make codebase-wiki-check-full`. This is a
source-only binding and proves nothing about a deployed version.
