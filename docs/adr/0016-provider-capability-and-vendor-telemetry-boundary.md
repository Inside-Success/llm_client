# ADR 0016: Provider Capability and Vendor Telemetry Boundary

Status: Accepted
Date: 2026-07-22
Applies to: Plan #110

## Context

`llm_client` exists so applications can use provider capabilities without
growing provider branches in every consumer. Two gaps made that boundary less
general than intended:

1. the public `reasoning_effort` option was forwarded only for hard-coded
   OpenAI and Anthropic families, even though OpenRouter and DeepSeek expose the
   same normalized control; and
2. required `task` and `trace_id` metadata reached local observability and
   LiteLLM callbacks, but not OpenRouter's native Broadcast trace envelope.

OpenRouter already normalizes reasoning controls and can broadcast request
traces to established observability backends. LiteLLM already owns commodity
transport normalization. Reimplementing either facility would add a second
capability matrix and a second telemetry exporter.

At the same time, vendor telemetry cannot replace local evidence. It does not
cover direct providers, workspace-agent SDKs, cache hits, pre-dispatch policy
failures, local schema validation, retry/fallback dispositions, or local budget
enforcement.

The user also requires Opus-family models to be unavailable through
`llm_client`, including workspace-agent aliases. A ban that applies only to raw
chat routes would be misleading.

## Decision

1. Normalized public controls are forwarded without a model-family allowlist.
   The selected provider/transport remains responsible for accepting or
   rejecting the control. `llm_client` must not silently discard it.
   When an installed LiteLLM capability table lags a documented OpenRouter
   normalized control, the OpenRouter transport declares that control through
   LiteLLM's `allowed_openai_params` compatibility seam.
2. The existing broad provider-kwargs surface remains the escape hatch for new
   provider features that do not yet have a normalized public option.
3. For OpenRouter calls, `llm_client` projects its required `task` and
   `trace_id` into OpenRouter's `trace` object without overwriting caller-owned
   trace fields. Account-side Broadcast configuration remains outside the
   library.
4. Local JSONL/SQLite evidence remains authoritative for `llm_client` execution
   semantics. OpenRouter logging/Broadcast and LiteLLM callbacks are optional,
   complementary projections.
5. Opus-family model IDs and aliases are hard-blocked before dispatch in every
   execution mode. The model registry, model-policy audit, public examples, and
   workflow defaults must not select Opus.
6. Claude workspace-agent defaults that previously selected Opus move to
   Sonnet. The ordinary `max_intelligence` tier selects the best remaining
   non-banned registered candidate under its existing ordering; this decision
   does not create a special replacement route.

## Borrow Versus Build

- **Borrow:** OpenRouter reasoning parameters, OpenRouter Broadcast/OTLP
  exporters, and LiteLLM provider transport.
- **Build:** small normalization/projection seams, invariant enforcement, local
  evidence, and deterministic contract tests.
- **Do not build:** another provider capability database, another OTLP
  exporter, or an OpenRouter-specific application client.

## Consequences

Positive:

1. Newly standardized controls can work without adding model-family branches.
2. OpenRouter users can enable existing observability destinations without
   application instrumentation while retaining local forensic evidence.
3. Opus cannot be reached indirectly through agent aliases or defaults.

Negative:

1. An unsupported normalized control now fails at the provider instead of being
   silently ignored.
2. Local and vendor traces may both exist and need a shared trace identifier.
3. Existing workflows that depended on Opus change model behavior when their
   defaults move to Sonnet.

## Testing Contract

1. Sync and async call preparation must forward DeepSeek/OpenRouter
   `reasoning_effort`.
2. OpenRouter calls must merge `task` and `trace_id` into Broadcast metadata
   while preserving explicit caller fields; non-OpenRouter calls must not gain
   the vendor envelope.
3. Raw Opus IDs, OpenRouter Opus IDs, and `claude-code/opus` must all fail before
   provider or agent dispatch.
4. Opus must not appear as a selectable packaged-registry model or workflow
   default.
5. Local observability tests remain unchanged and green.
