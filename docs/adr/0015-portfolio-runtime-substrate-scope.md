# ADR 0015: Present LLM Client As Runtime Substrate Evidence

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Status

Accepted.

## Context

`llm_client` is central shared infrastructure, but infrastructure alone is
often weak portfolio evidence. A reviewer may not care that many API surfaces
exist unless those surfaces make an applied system easier to inspect, govern,
or improve.

The repo already owns the cross-project runtime and observability substrate.
Adjacent projects own prompt evaluation, retrieval, qualitative analysis,
workflow orchestration, and applied analytic claims.

## Decision

Portfolio surfaces should present `llm_client` as supporting runtime evidence:

- lead with applied traces where observability changed an engineering decision;
- show cost, latency, route, error, structured-output, and trace data when
  making reliability claims;
- describe API breadth as enabling infrastructure, not as the main achievement;
- leave prompt-evaluation semantics to `prompt_eval`;
- leave project-specific analysis, retrieval, and coding logic to consuming
  projects;
- leave durable workflow orchestration above this runtime layer unless a
  separate ADR changes that boundary.

## Consequences

Benefits:

- makes the portfolio story understandable to non-infrastructure reviewers;
- prevents runtime work from being mistaken for analyst-facing product work;
- keeps ownership boundaries aligned with existing ADRs;
- creates a clear evidence path through downstream applied traces.

Costs:

- the repo's standalone page must be modest about claims;
- strongest evidence depends on downstream project traces;
- API breadth cannot be used as a substitute for applied outcomes.

## Controls

- [docs/APPLIED_OBSERVABILITY_CASE.md](../APPLIED_OBSERVABILITY_CASE.md)
  defines the applied portfolio case shape.
- [docs/REQUIREMENTS.md](../REQUIREMENTS.md) defines scope and non-goals.
- [docs/ops/CAPABILITY_DECOMPOSITION.md](../ops/CAPABILITY_DECOMPOSITION.md)
  defines ownership boundaries.
- [docs/VALIDATION.md](../VALIDATION.md) separates runtime evidence from
  downstream analytic validation.
