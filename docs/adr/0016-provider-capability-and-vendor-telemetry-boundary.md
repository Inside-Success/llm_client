# ADR 0016: Provider Capability and Vendor Telemetry Boundary

Status: Accepted
Date: 2026-07-22
Applies to: Plan #110

## 2026-07-23 Amendment: Exact Model Execution Allowlist

Plan #115 supersedes this ADR's ban-oriented model-selection policy while
preserving its provider-capability and telemetry decisions.

For callers using `model_policy="enforce_allowlist"`, `llm_client` evaluates the
entire canonical primary/fallback chain against one exact shared allowlist
before dispatch. DeepSeek V4 Flash is the sole no-justification default. Every
other allowed route requires a non-empty `model_justification`, which is
retained in the routing trace and replayable call snapshot. A justification
cannot authorize an unlisted model.

Existing callers temporarily remain in `compatibility` mode until individually
audited and migrated; newly migrated production paths must use enforcement.
This staged transition avoids silently breaking unrelated consumers while
making the target invariant explicit. GPT-5 Mini and GPT-5.1 Mini are not
allowlisted.

The statement below that normalized public controls are forwarded “without a
model-family allowlist” refers only to capability-specific branching after
model authorization. It no longer means arbitrary models may execute.

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
chat routes would be misleading. OpenRouter Auto Router, presets, and provider
fallback arrays can select a final model after the primary model string is
checked, so opaque model selection is also inside the ban's threat model.

## Decision

1. Normalized public controls are forwarded without a model-family allowlist.
   The selected provider/transport remains responsible for accepting or
   rejecting the control. `llm_client` must not silently discard it.
   When an installed LiteLLM capability table lags a documented OpenRouter
   normalized control, the OpenRouter transport declares that control through
   LiteLLM's `allowed_openai_params` compatibility seam and sets
   `provider.require_parameters=true`. A caller may still choose provider
   sorting and fallback policy, but may not opt into silently ignored controls.
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
6. Every resolved fallback leg is checked. OpenRouter Auto Router, presets, and
   the auto-router plugin are rejected because their candidate sets are not
   locally inspectable; provider `models`/`fallbacks` arrays are accepted only
   when they contain no banned or opaque selector. Fixed-model provider sorting
   remains supported. Account Guardrails are recommended defense in depth, not
   a substitute for local enforcement.
7. Claude workspace-agent defaults that previously selected Opus move to
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
3. Opus cannot be reached indirectly through agent aliases, defaults,
   fallbacks, Auto Router, or presets.

Negative:

1. An unsupported normalized control now fails at the provider instead of being
   silently ignored.
2. Local and vendor traces may both exist and need a shared trace identifier.
3. Existing workflows that depended on Opus change model behavior when their
   defaults move to Sonnet.
4. Callers cannot use account-side model selectors while the non-overridable
   local model ban is active; they must request an explicit model.

## Testing Contract

1. Sync and async call preparation must forward DeepSeek/OpenRouter
   `reasoning_effort`.
2. OpenRouter calls must merge `task` and `trace_id` into Broadcast metadata
   while preserving explicit caller fields; non-OpenRouter calls must not gain
   the vendor envelope.
3. Raw Opus IDs, OpenRouter Opus IDs, `claude-code/opus`, Opus fallback legs,
   Auto Router, and presets must all fail before provider or agent dispatch.
4. Opus must not appear as a selectable packaged-registry model or workflow
   default.
5. Local observability tests remain unchanged and green.
6. OpenRouter reasoning controls must set `provider.require_parameters=true`,
   preserve other provider-routing fields, and reject an explicit false value.
