# LLM Client Validation Register

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Validation Position

`llm_client` has implementation evidence for shared runtime behavior and an
applied-case pattern for observability. It still needs a fully populated
downstream trace to become strong standalone portfolio evidence.

The key distinction:

- **runtime-valid:** model calls execute through the shared API and return
  expected result metadata;
- **trace-valid:** cost, latency, tokens, route, error, schema validation, and
  trace context are inspectable;
- **decision-valid:** a downstream project uses the trace to make or justify an
  engineering decision;
- **analysis-valid:** the downstream project correctly supports an analytic
  claim.

This repo owns runtime-valid and trace-valid evidence. Applied projects own the
decision-valid and analysis-valid layers.

## Current Evidence

| Evidence area | Current artifact | Claim licensed |
|---|---|---|
| Runtime API | `README.md` and `docs/API_REFERENCE.md` | Core call surfaces and result fields are documented. |
| Requirements | `docs/REQUIREMENTS.md` | Required metadata, observability, model registry, and non-goals are explicit. |
| Applied case shape | `docs/APPLIED_OBSERVABILITY_CASE.md` | Portfolio evidence should be tied to downstream decisions. |
| Runtime substrate ADR | `docs/adr/0010-cross-project-runtime-substrate.md` | Cross-project ownership is explicit. |
| Observability ADR | `docs/adr/0007-observability-contract-boundary.md` | Logging/persistence boundary is explicit. |
| Capability ownership | `docs/ops/CAPABILITY_DECOMPOSITION.md` | Adjacent repo boundaries are documented. |

## Evidence Not Yet Present

Do not claim the following without new evidence:

- observability proves a downstream analytic claim;
- this repo is a complete agent framework or workflow engine;
- prompt optimization belongs here rather than in `prompt_eval`;
- current model policy is universally best for every task;
- API breadth is sufficient portfolio evidence without an applied trace.

## Commands

Core checks:

```bash
make test
make lint
make typecheck
python scripts/check_markdown_links.py PROJECT.md docs/METHODOLOGY.md docs/ARTIFACTS.md docs/VALIDATION.md docs/CONCERNS.md docs/adr/0015-portfolio-runtime-substrate-scope.md docs/wiki_manifest.yaml
git diff --check
```

Evidence queries:

```bash
make cost-by-task DAYS=7
make errors DAYS=7
make traces DAYS=3
```

Use real observability queries for cost and error claims. Do not estimate.

## Portfolio Readiness Gate

The repo is portfolio-ready as supporting infrastructure when framed with its
current caveats. It becomes stronger externally when it has:

1. One applied downstream trace.
2. A table mapping trace signal to engineering decision.
3. A before/after validation or diagnostic improvement.
4. A consumer note tying the infrastructure to applied project evidence.
