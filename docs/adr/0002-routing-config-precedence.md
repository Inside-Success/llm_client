# ADR 0002: Routing and Config Precedence

Status: Accepted
Date: 2026-02-22
Last verified: 2026-07-14
Verification context: selected-attempt receipts and exact raw-artifact reads verify sync/async retry and fallback model transitions without changing call/config routing precedence; v3 replay retains caller-selected retry/fallback/cache controls.

## Context

Routing behavior has been sensitive to environment defaults. This creates drift
between local runs, CI, and tests when policy is not explicitly set.

## Decision

1. Routing-sensitive tests must set routing policy explicitly.
2. Tests must not rely on ambient environment defaults.
3. Routing behavior contracts are validated under explicit policy fixtures.
4. Week 1 does not flip runtime routing defaults.

## Precedence Rule (target contract)

For any configurable routing option:
1. Explicit call/site config wins.
2. Explicit test fixture/env override is second.
3. Library defaults are last.

## Rationale

This prevents silent behavior drift and makes failures reproducible.

## Consequences

Positive:
1. Deterministic tests and clearer regression attribution.
2. Safer staged refactor to pure router extraction.

Negative:
1. More explicit setup in tests.

## Follow-up

Week 2+: extract pure routing resolver with typed output:
`resolve_call(request, config) -> ResolvedCallPlan`.

Verification context (2026-07-13): the resolved fallback order now determines
globally increasing structured-attempt ordinals. This adds observability of the
existing route; it does not change configuration precedence.

The runtime now treats a validated native-schema response as terminal for model
fallback; this is an execution-integrity boundary, not a new routing precedence.
