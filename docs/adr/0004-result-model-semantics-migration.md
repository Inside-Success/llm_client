# ADR 0004: Fixed `result.model` Semantics

Status: Accepted
Date: 2026-02-23
Last verified: 2026-07-14
Verification context: additive `LLMCallResult.logical_call_id` binds a structured result to trusted-process receipt and opt-in exact raw-content evidence without changing `model`, requested/resolved model semantics, or routing traces; focused sync/async controls pass.

## Context

`LLMCallResult.model` had compatibility modes and migration toggles. This made
debugging harder and forced callers to know mode-specific behavior.

## Decision

1. Remove semantics-mode switching.
2. Remove semantics telemetry and related CLI reporting commands.
3. Use one identity contract everywhere:
   - `result.model`: terminal executed model.
   - `result.requested_model`: caller input model.
   - `result.resolved_model` / `result.execution_model`: terminal executed model.
   - `result.routing_trace`: routing/fallback explanation.

## Consequences

Positive:
1. No ambiguity in `result.model`.
2. No mode/env drift between environments.
3. Simpler client API and docs.

Negative:
1. Breaking change for clients that relied on legacy/model-mode behavior.
2. Removed mode-adoption telemetry and semantics report commands.

## Rollout

1. Version cut to `0.7.0`.
2. Keep additive identity fields and routing trace as the canonical debugging
   surface.

## Testing Contract

1. Identity tests assert `result.model == result.resolved_model` when resolved
   identity is known.
2. MCP/agent tests assert fallback cases still preserve:
   - `requested_model` as caller input.
   - `routing_trace` attempted model chain.

Verification context (2026-07-13): structured-attempt child events expose the
per-attempt model and global ordinal needed to diagnose fallback, without
changing `LLMCallResult.model`, `requested_model`, or `routing_trace`.

Post-validation finalization cannot switch models, preserving the executed
model identity attached to the already-validated result.
