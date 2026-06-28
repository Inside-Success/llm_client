# LLM Client Artifact Register

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Primary Reviewer Artifacts

| Artifact | Role | Portfolio meaning |
|---|---|---|
| [PROJECT.md](../PROJECT.md) | Dossier entrypoint | Frames `llm_client` as supporting runtime infrastructure. |
| [README.md](../README.md) | Project overview | Public API, examples, observability CLI, and usage. |
| [docs/APPLIED_OBSERVABILITY_CASE.md](APPLIED_OBSERVABILITY_CASE.md) | Portfolio guide | Explains how traces become evidence through applied decisions. |
| [docs/REQUIREMENTS.md](REQUIREMENTS.md) | Requirements | Scope, non-goals, API contract, and consumers. |
| [docs/API_REFERENCE.md](API_REFERENCE.md) | API reference | Generated public surface summary. |
| [docs/ops/CAPABILITY_DECOMPOSITION.md](ops/CAPABILITY_DECOMPOSITION.md) | Ownership ledger | Defines runtime vs prompt-eval vs governance boundaries. |
| [docs/METHODOLOGY.md](METHODOLOGY.md) | Methodology spine | Explains runtime-substrate method and failure modes. |
| [docs/VALIDATION.md](VALIDATION.md) | Validation register | Separates runtime evidence from downstream analytic proof. |
| [docs/CONCERNS.md](CONCERNS.md) | Concern register | Tracks open portfolio and architecture risks. |

## Code And Execution Surfaces

| Surface | Role |
|---|---|
| `llm_client/client.py` and runtime modules | Public sync/async call surfaces and orchestration. |
| `llm_client/models.py` | Result and request model contracts. |
| `llm_client/observability/` | Cost, trace, run, and diagnostic logging surfaces. |
| `llm_client/model_registry.py` and packaged config | Task-based model selection. |
| `llm_client/tools/` | Tool-call registration and observability surfaces. |
| `llm_client/prompts/` | Prompt rendering and explicit prompt identity support. |
| `docs/adr/` | Architecture decisions for model identity, observability, runtime boundary, and related policies. |
| `tests/` | Runtime, observability, schema, and compatibility tests. |

## Evidence Artifacts

| Artifact | Evidence | Notes |
|---|---|---|
| [docs/APPLIED_OBSERVABILITY_CASE.md](APPLIED_OBSERVABILITY_CASE.md) | Portfolio framing | Best reviewer-facing case shape. |
| [docs/REQUIREMENTS.md](REQUIREMENTS.md) | Runtime contract | Defines required metadata and non-goals. |
| [docs/adr/0010-cross-project-runtime-substrate.md](adr/0010-cross-project-runtime-substrate.md) | Runtime ownership | Establishes cross-project substrate boundary. |
| [docs/adr/0007-observability-contract-boundary.md](adr/0007-observability-contract-boundary.md) | Observability boundary | Defines persistence and compatibility posture. |
| [docs/ops/CAPABILITY_DECOMPOSITION.md](ops/CAPABILITY_DECOMPOSITION.md) | Capability ownership | Prevents reabsorbing prompt evaluation or project logic. |

## Missing Portfolio Artifacts

- One concrete downstream trace where cost, error, latency, or structured-output
  validation changed an engineering decision.
- A compact before/after table showing the trace signal and resulting fix.
- A consumer integration note from AC15, Grounded Research, Qualitative Coding,
  or another applied project.
- A small screenshot or exported report from the observability CLI/dashboard.
