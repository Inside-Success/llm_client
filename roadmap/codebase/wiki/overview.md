---
type: overview
title: llm_client Overview
description: The repository's role, main capabilities, boundaries, and shortest useful reading paths.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../CLAUDE.md, ../../../docs/ops/CAPABILITY_DECOMPOSITION.md, sources/revision-f194028.md]
confidence: high
---

# Summary

`llm_client` is a shared runtime and control plane for LLM work. A consumer
supplies messages, a model request, task/trace identity, and a budget. The
library applies model policy, selects a transport, handles retries and
fallbacks, validates structured outputs when requested, and returns a typed
result with routing and cost metadata. It also owns durable observability,
replay-oriented call snapshots, agent/tool runtime plumbing, prompt assets,
streaming, batching, and embeddings.

It is deliberately not an application-specific retrieval system, an evaluation
rubric engine, or the owner of ecosystem governance. Those boundaries are
maintained in the [capability decomposition at the pinned revision](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/docs/ops/CAPABILITY_DECOMPOSITION.md)
and summarized in [Architecture](architecture.md).

## Mental model

```text
consumer
  -> public typed facade
  -> call envelope and policy
  -> routing + retry/fallback execution
  -> provider / Responses / agent runtime
  -> result finalization + durable evidence
```

Read [Public API and contracts](concepts/public-api-and-contracts.md) to choose
an entrypoint, then follow either the [text](workflows/text-call-lifecycle.md)
or [structured](workflows/structured-call-lifecycle.md) execution path. Use the
[package map](packages/package-map.md) when locating ownership for a change.

# Authority boundary

This page is derived from source and repository authority at revision
`f194028`. Runtime availability, current provider behavior, deployed versions,
and database contents require fresh observation and are not established here.

# Citations

1. [`llm_client/__init__.py` public-facade description at `f194028`](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/__init__.py#L1-L62)
2. [Repository capability ownership at `f194028`](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/docs/ops/CAPABILITY_DECOMPOSITION.md)
3. [Pinned capsule ingest](sources/revision-f194028.md)
