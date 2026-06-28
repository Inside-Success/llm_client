# Agent Collaboration Workflows

This branch packages the local work for replacing manual paste-between-agent
loops with `llm_client` workflows that call agent models directly and write
structured artifacts to disk.

## Install

From this checkout:

```bash
pip install -e ".[workflow,structured,agents,codex]"
```

Use the same auth that the agent SDKs expect for the selected models. The
examples below assume `codex/gpt-5.4` and `claude-code/opus` are available in
your local agent environment.

## Choose The Workflow

Use `duet-review` when one agent has produced a plan or implementation and the
other agent should review it against explicit criteria. It runs a reviewer-only
pass against existing artifacts.

Use `review-artifact` when the foreground agent should keep working while a
background reviewer critiques a patch, plan, decision, or other text artifact.
This is the smallest replacement for "paste this into the other terminal and
ask for review."

Use `deliberate-task` when two agents should independently analyze the same
question, read each other's positions, and converge or preserve a productive
disagreement.

## Review A Plan And Diff

```bash
python -m llm_client duet-review \
  --plan-doc docs/plans/33_deliberation_workflow.md \
  --workspace "$PWD" \
  --out runs/my-duet-review \
  --task-title "Review the deliberation plan" \
  --task-goal "Find ungrounded claims, missing tests, and scope drift" \
  --task-family plan_doc_review \
  --impl-base origin/main \
  --impl-head HEAD \
  --impl-files llm_client/workflow/deliberate.py llm_client/cli/deliberate.py
```

Outputs:

- `task.json`
- `plan_review.json`
- `implement.md` and `implement.json` when `--impl-base` is provided
- `implement_review.json` when implementation review runs

Built-in task families are `generic`, `plan_doc_review`, and `twin_update`.

## Run A Background Artifact Review

```bash
git diff origin/main...HEAD > /tmp/agent-collab.patch

python -m llm_client review-artifact \
  --artifact-file /tmp/agent-collab.patch \
  --artifact-label "agent collaboration package" \
  --context-text "Review the packaged Claude/Codex collaboration workflow for correctness, missing docs, and scope drift." \
  --reviewer claude-code/opus \
  --workspace "$PWD" \
  --out runs/background-review-agent-collab/review.json &
```

The command writes one `AdversarialReview` JSON file. Run it in the background
when the caller can continue on other work and inspect the review at the next
checkpoint.

## Deliberate On A Question

Create a task file:

```json
{
  "task_id": "agent-collab-shape",
  "title": "Choose the collaboration topology",
  "question": "Should this work use asymmetric duet review, symmetric deliberation, or both?",
  "success_criteria": [
    "Name the recommended topology",
    "List risks and tests",
    "Preserve any unresolved disagreement"
  ],
  "constraints": [
    "Ground claims in repository files when possible"
  ]
}
```

Run the debate:

```bash
python -m llm_client deliberate-task \
  --task-file task.json \
  --workspace "$PWD" \
  --out runs/my-deliberation \
  --agents agent_a:codex/gpt-5.4,agent_b:claude-code/opus \
  --max-rounds 3 \
  --synthesis-model claude-code/opus
```

Outputs include per-round positions, verifier ledgers when enabled, synthesis,
and signoff artifacts.

## Evidence In This Branch

Tracked examples under `runs/` show prior dogfood runs:

- `runs/background-review-demo/`
- `runs/plan-33-self-deliberation*/`
- `runs/plan-35-barrier-pilot/`

New local run output is ignored by default. Commit curated evidence with
`git add -f runs/<name>/...` when it should travel with the branch.

## Design References

- `docs/plans/29_implementer_reviewer_duet.md`
- `docs/plans/30_duet_autonomous_hardening.md`
- `docs/plans/31_task_family_abstraction.md`
- `docs/plans/32_twin_update_profile.md`
- `docs/plans/33_deliberation_workflow.md`
- `docs/plans/34_deliberation_verifier_adjudicator.md`
- `docs/plans/35_deliberation_within_round_barrier_protocol.md`
