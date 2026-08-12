# Run Artifacts

This directory holds curated dogfood evidence for the agent-collaboration
workflows. Most new `runs/` output is local scratch and is ignored by default.

Commit only evidence that helps a future reader understand or reproduce a
workflow decision. Use `git add -f runs/<name>/...` for intentional additions.

## Model experiments

Reusable model comparisons live under `runs/model-experiments/<experiment-id>/`
as a `record.json` that validates against
`docs/schemas/model-experiment-record-v1.schema.json`. Keep task-specific bulk
data and raw outputs with their owning project; reference them here with a
logical URI and SHA-256 digest.

A reusable record must identify the exact route and reasoning effort, frozen
dataset and contracts, retries and all-attempt cost scope, latency, token/cache
accounting, per-item comparison, decision, and non-claims. Observed provider
billing and time-sensitive list-price snapshots are separate evidence.
