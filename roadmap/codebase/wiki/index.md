# llm_client Codebase Wiki

Start here for architecture and code-navigation questions. This is a compiled,
interlinked explanation of the complete Python repository at revision
`c2f3693a7a8f1f2e211368c189a64df69dcb381f`. It is derived orientation: follow
its links, then reopen native source before changing code or making an exact
claim.

## First reads

| Question | Read |
| --- | --- |
| What is this repository and what does it own? | [Overview](overview.md) |
| How do the main layers connect? | [Architecture](architecture.md) |
| Where does each of the 155 Python files belong? | [Package map](packages/package-map.md) |
| What happens during a normal text call? | [Text-call lifecycle](workflows/text-call-lifecycle.md) |
| What happens during a typed structured call? | [Structured-call lifecycle](workflows/structured-call-lifecycle.md) |
| Why are there personal and company repositories? | [Personal and Inside Success lineage](lineage/personal-and-inside-success.md) |

## Concepts

- [Public API and contracts](concepts/public-api-and-contracts.md) — stable entrypoints, typed results, and consumer-facing boundaries.
- [Model selection and routing](concepts/model-selection-and-routing.md) — requested models, normalization, execution policy, and fallback chains.
- [Structured output](concepts/structured-output.md) — Pydantic validation, native schemas, Instructor fallback, and evidence custody.
- [Observability and budgets](concepts/observability-and-budgets.md) — traces, lifecycle events, cost settlement, replay, and outer runs.
- [Prompt assets](concepts/prompt-assets.md) — versioned YAML/Jinja prompts and their identity in traces.
- [Agents and tools](concepts/agents-and-tools.md) — agent SDK dispatch, MCP loops, tool contracts, and tool observability.

## Source and maintenance

- [Revision `c2f3693` source ingest](sources/revision-c2f3693.md) — current source, capsule verification, provenance, and limits.
- [Revision `f194028` base capsule](sources/revision-f194028.md) — accepted Project Meta capsule retained as prior source evidence.
- [Update log](log.md) — ingests, queries filed back, and lint results.

The wiki indexes the full repository at package level and deepens the most
important cross-package flows. It does not reproduce 1,079 symbol records as
Markdown pages; those remain in the revision-bound capsule and are opened only
when a question needs that level of detail.
