# Documentation

Status: active.

Architecture, plans, ADRs, guides, API reference, and ownership remain in this
existing directory. Start with `plans/AGENTS.md` and
`ops/CAPABILITY_DECOMPOSITION.md`; this front door does not duplicate authority.

Wiki route: [wiki/index.md](../wiki/index.md) is the repository front door.

## Documents in this directory

| Need | Read |
| --- | --- |
| Plans, delivery status, ADRs | [plan index](plans/AGENTS.md), [completed plans](plans/COMPLETED_PLANS.md), [ADR index](adr/README.md), [ADR texts](adr/DECISIONS.md), [ADR rules](adr/AGENTS.md) |
| Run and operational evidence | [runs/RUNS.md](runs/RUNS.md) (one section per dated probe, certification or inventory; add new records as sections) |
| What `llm_client` owns | [CAPABILITY_DECOMPOSITION](ops/CAPABILITY_DECOMPOSITION.md), [ECOSYSTEM_TOP_DOWN_ARCHITECTURE](ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md) |
| Requirements, methodology, validation | [REQUIREMENTS](REQUIREMENTS.md), [METHODOLOGY](METHODOLOGY.md), [VALIDATION](VALIDATION.md) |
| Artifact and prompt-size contracts | [ARTIFACTS](ARTIFACTS.md), [PROMPT_SIZE_CONTRACTS](PROMPT_SIZE_CONTRACTS.md) |
| Local-model parity, applied observability | [LOCAL_MODEL_PARITY_V0](LOCAL_MODEL_PARITY_V0.md), [APPLIED_OBSERVABILITY_CASE](APPLIED_OBSERVABILITY_CASE.md) |
| Open concerns, generated API reference | [CONCERNS](CONCERNS.md), [API_REFERENCE](API_REFERENCE.md) |
| Usage guides | [model selection](guides/model-selection.md), [advanced usage](guides/advanced-usage.md), [Codex](guides/codex-integration.md), [agent collaboration](guides/agent-collaboration.md), [MCP agents](guides/mcp-agent-contracts.md), [experiments](guides/experiment-observability.md), [observed runs](guides/observed-runs.md) |
| Subtree rules | [llm_client](../llm_client/AGENTS.md): [agent](../llm_client/agent/AGENTS.md), [cli](../llm_client/cli/AGENTS.md), [core](../llm_client/core/AGENTS.md), [execution](../llm_client/execution/AGENTS.md), [observability](../llm_client/observability/AGENTS.md), [prompts](../llm_client/prompts/AGENTS.md), [sdk](../llm_client/sdk/AGENTS.md), [tools](../llm_client/tools/AGENTS.md), [utils](../llm_client/utils/AGENTS.md); [tests](../tests/AGENTS.md), [scripts](../scripts/AGENTS.md), [ui](../ui/AGENTS.md); [codebase wiki schema](../roadmap/codebase/AGENTS.md) |
| Directory READMEs | [src](../src/README.md), [tests](../tests/README.md), [ui](../ui/README.md), [runs](../runs/README.md), [generated](../generated/README.md), [misc](../misc/README.md) |
