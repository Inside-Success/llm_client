# llm_client Codebase Wiki

Start here for architecture and code-navigation questions. This is a compiled,
interlinked explanation of the complete Python repository at revision
`4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd`. It is derived orientation: follow
its links, then reopen native source before changing code or making an exact
claim.

## First reads

| Question | Read |
| --- | --- |
| What is this repository and what does it own? | [Overview](overview.md) |
| How do the main layers connect? | [Architecture](architecture.md) |
| Where does each of the 165 Python files belong? | [Package map](packages/package-map.md) |
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

- [Revision `4f7ecfa` source ingest](sources/revision-4f7ecfa.md) — current source, exact Codex CLI JSONL custody, provenance, and limits.
- [Revision `657a98f` source ingest](sources/revision-657a98f.md) — prior Python compatibility binding.
- [Revision `917318b` source ingest](sources/revision-917318b.md) — exact Codex-session seam and provider-free evidence.
- [Revision `c2f3693` capsule ingest](sources/revision-c2f3693.md) — prior verified personal capsule evidence.
- [Inside Success revision `f4a08fe` source ingest](sources/inside-success-f4a08fe.md) — separate company capsule, exact downstream differences, and provenance limits.
- [Revision `f194028` base capsule](sources/revision-f194028.md) — accepted Project Meta capsule retained as prior source evidence.
- [Update log](log.md) — ingests, queries filed back, and lint results.

The wiki indexes the full repository at package level and deepens the most
important cross-package flows. Detailed symbol records remain in the older
revision-bound capsules and are reopened only when a question needs that level
of detail; exact current claims return to native source at `4f7ecfa`.
