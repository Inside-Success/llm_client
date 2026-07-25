# Supporting Prior Art for Plan #36: `utils/consensus_system`

This note records the useful ideas extracted from the legacy
`~/projects/utils/consensus_system/` repo before archive or tombstone work. It
is not a plan to keep that repo as an active runnable implementation.

## Source Inspected

- `README.md`
- `consensus_system.py`
- `consensus_analyzer.py`
- `run_consensus.py`
- demo and quick-test entry points

## Preserved Concepts

| Concept | What the legacy code did | Why it matters | Replacement surface |
|---------|--------------------------|----------------|---------------------|
| Convergence / disagreement representation | Each round stored pairwise similarity judgments and an `average_divergence` value. The final report included a `convergence_timeline`, convergence status, and divergence history. | A review system should distinguish "all reviewers now agree" from "the budget stopped while disagreement remains." That is a validity signal, not just a UX metric. | `review-cycle` already has deterministic stop reasons and repeated-actionable-finding digests. Future evaluation/observability should add a disagreement timeline over normalized findings, sourced from `AdversarialReview` and `ReviewCycleSignoff` artifacts rather than free-form similarity JSON. |
| Opinion dynamics / confidence reporting | `AnalysisResponse` carried `confidence_level`; `_detect_opinion_shifts` compared conclusion changes and confidence deltas; `consensus_analyzer.py` plotted confidence evolution and reported model stability. | Confidence shifts can reveal whether a model changed its view because of evidence, stagnated, or became overconfident without new support. This is useful for evaluating review cycles and deliberations. | `llm_client` observability supplies actual model/cost/latency traces. Review confidence should be represented as evaluator metrics in `prompt_eval` case sets or a future review-cycle metric artifact, not as ad hoc model self-confidence driving control flow. |
| Influence and opinion-leader signal | `SimilarityJudgment.influence_detected` and `influence_direction` were aggregated into `opinion_leaders` and most-influential / most-influenced model summaries. | Influence tracking helps detect collapse into model imitation, especially in multi-model discussions where independence is supposed to carry epistemic value. | Plan #35's barrier/anonymization protocol protects independence before comparison. A future `deliberate-task` evaluator can compute influence/collapse metrics from anonymized turn artifacts. It should not revive peer-visible consensus rounds as the default. |
| Debate turn topology / round structure | The system ran an independent initial round followed by meta-analysis rounds where each model reviewed other models' responses, then stopped on convergence, stagnation, or max rounds. | The useful idea is the bounded round topology: independent estimates first, then structured comparison, then explicit stop reason. | `deliberate-task` owns symmetric multi-agent debate. `review-cycle` owns review/apply/review for artifact improvement. They should remain separate because consensus over answers and iterative artifact repair have different state machines. |
| Summarization / synthesis artifact shape | The final report included metadata, per-round responses, final positions, key points, convergence summary, and opinion leaders; JSON exports were timestamped for later inspection. | Durable synthesis artifacts are required for agent handoff and later audit. | `review-cycle` writes `review_N.json`, `apply_N.*`, `diff_N.patch`, `discussion_queue*.json`, `budget_ledger.json`, and `signoff.json`. OpenClaw links those artifacts through a sidecar rather than embedding review semantics in task reports. |
| Evaluation metrics not already covered | Legacy metrics included initial/final divergence, convergence rate, peak divergence, stagnation points, turning points, total opinion shifts, stability scores, and confidence evolution. | These are useful evaluation dimensions, but not runtime correctness contracts. They help compare review profiles and model pairings after artifacts exist. | `prompt_eval` should own frozen-case metrics for missed defects, false positives, actionable-finding stability, and any added disagreement/confidence metrics. `AdversarialReview` remains the review contract; it should not grow consensus-only analytics fields. |

## Ideas Not Preserved as Runtime Code

- Direct `litellm` and dotenv-based provider calls are replaced by
  `llm_client` routing, required `task`, `trace_id`, and `max_budget`
  metadata, budget ledgers, and shared observability.
- Free-form schema dictionaries are replaced by Pydantic models and JSON Schema
  response formats.
- Consensus stopping by self-reported confidence is not preserved. Runtime stop
  conditions stay deterministic: pass/no-actionable, repeated digest, no diff,
  max cycles, or budget exhaustion.
- Peer-visible meta-analysis is not the default because it can collapse
  independent estimates. If used, it belongs behind the deliberate workflow's
  barrier/anonymization controls.

## Archive Decision

`consensus_system` is prior art, not the canonical intermodel collaboration
surface. The concepts above are covered by current or planned `llm_client`,
`prompt_eval`, and OpenClaw surfaces. The remaining runnable code is duplicate
legacy infrastructure and should be tombstoned in place or moved to
`~/projects/PROJECTS_DEFERRED/intermodel-dialogue-legacy/` only after the
sibling repo's branch, remote, and visibility are verified.
