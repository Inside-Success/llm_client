# Experiment Observability

## Recording experiments

Use one run per condition. Keep the dataset, scenario, phase, item IDs, and
metrics schema stable across the comparison. `start_run`, `log_item`, and
`finish_run` are keyword-only APIs.

```python
import time

from llm_client import acall_llm_structured, finish_run, log_item, start_run

run_id = start_run(
    dataset="frozen-corpus:v2",
    model="openrouter/openai/gpt-5.6-luna",
    task="example.extraction",
    condition_id="baseline",
    scenario_id="extraction-contract-v2",
    phase="model-routing",
    metrics_schema=["contract_valid", "review_accepted"],
    config={"reasoning_effort": "medium", "temperature": 0.1},
    provenance={
        "dataset_sha256": "<sha256>",
        "prompt_sha256": "<sha256>",
        "schema_sha256": "<sha256>",
    },
)

for item in dataset:
    trace_id = f"{run_id}/{item.id}"
    started = time.monotonic()
    parsed, metadata = await acall_llm_structured(..., trace_id=trace_id)
    log_item(
        run_id=run_id,
        item_id=item.id,
        predicted=parsed.model_dump_json(),
        metrics={
            "contract_valid": 1.0,
            "review_accepted": float(review.accepted),
        },
        latency_s=time.monotonic() - started,
        cost=metadata.cost,
        trace_id=trace_id,
    )

finish_run(
    run_id=run_id,
    summary_metrics={"decision_ready": True},
)
```

For an agent task subject to AgentSpec enforcement, also pass `agent_spec=` or
an explicit, reasoned opt-out. Do not silently disable the enforcement policy.

## Making a comparison reusable

The experiment database is the query surface for run and item telemetry. A
curated cross-project decision also needs a portable record that explains what
the numbers license. Validate committed records against
`docs/schemas/model-experiment-record-v1.schema.json`.

At minimum, retain:

- the decision question, experimental stage, licensed claim, and non-claims;
- a frozen dataset ID, selection method, unit of analysis, and content hashes;
- exact requested and resolved routes, reasoning effort, prompt/schema/config
  identity, and repository/runtime revisions;
- logical calls, provider attempts, retries, terminal errors, wall latency,
  tokens, cached tokens, and response-cache hits;
- observed provider-billed cost with its scope, separate from a dated external
  list-price snapshot or projection;
- deterministic contract results, independent-review coverage, and item-level
  disagreements;
- stable artifact references with SHA-256 digests; and
- the signed decision, rationale, and evidence required to revisit it.

Do not copy bulk corpora or task-owned outputs into `llm_client`. Keep them with
their owner and use a logical URI plus digest. `prompt_eval` continues to own
rubrics, statistical comparison, and evaluation aggregation.

The reference instance is
`runs/model-experiments/process-tracing-revolution-adjudication-2026-08-12/record.json`.
It deliberately records a narrow no-switch decision rather than claiming that
one model is globally better.

```bash
python -m jsonschema \
  --instance runs/model-experiments/process-tracing-revolution-adjudication-2026-08-12/record.json \
  docs/schemas/model-experiment-record-v1.schema.json
```

## CLI commands

```bash
# List experiments
python -m llm_client experiments

# Filter by condition/scenario
python -m llm_client experiments --condition-id forced_off --scenario-id phase1

# Compare two runs
python -m llm_client experiments --compare RUN_BASE RUN_CANDIDATE

# Compare cohorts
python -m llm_client experiments --compare-cohorts baseline forced_reduced forced_off \
    --baseline-condition-id baseline --scenario-id phase1 --phase phase1

# Detailed run view with triage
python -m llm_client experiments --detail RUN_ID

# Deterministic checks
python -m llm_client experiments --detail RUN_ID --det-checks default

# Rubric-based LLM review
python -m llm_client experiments --detail RUN_ID --review-rubric extraction_quality

# Policy gates (CI-friendly)
python -m llm_client experiments --detail RUN_ID \
    --gate-policy '{"pass_if":{"avg_llm_em_gte":80}}' \
    --gate-fail-exit-code
```

## Adoption gates

For long-thinking adoption telemetry:

```python
from llm_client import get_background_mode_adoption

summary = get_background_mode_adoption(
    experiments_path="~/projects/data/task_graph/experiments.jsonl",
    run_id_prefix="nightly_",
)
print(summary["background_mode_rate_among_reasoning"])
```

CLI gate (cron/CI-friendly):

```bash
python -m llm_client adoption --run-id-prefix nightly_ --format table
python -m llm_client adoption --run-id-prefix nightly_ --since 2026-02-20 \
    --min-rate 0.95 --metric among_reasoning --min-samples 20

# Or via wrapper script:
./scripts/adoption_gate.sh
```

## Eval helpers

```python
from prompt_eval.experiment_eval import (
    build_gate_signals,
    extract_agent_outcome,
    summarize_agent_outcomes,
)

outcome = extract_agent_outcome(item_result)
summary = summarize_agent_outcomes(run_items)
signals = build_gate_signals(run_info=run_info, items=run_items)
```
