# Plan #36 Prior Art: `agent_ontology/agents/debate_agent.py`

This note records the useful ideas extracted from
`~/projects/agent_ontology/agents/debate_agent.py` before archive or tombstone
work. The inspected file is a generated pro/con debate state machine; it is not
the canonical runtime for intermodel collaboration.

## Source Inspected

- `agents/debate_agent.py`

## Preserved Concepts

| Concept | What the legacy code did | Why it matters | Replacement surface |
|---------|--------------------------|----------------|---------------------|
| Debate turn topology | The state machine framed a topic with a moderator, initialized a proposition, alternated pro and con turns for bounded rounds, then sent the full history to a judge. | The useful topology is role-separated argument generation followed by adjudication. This is the same class of work as model deliberation, not artifact repair. | `deliberate-task` owns symmetric debate and multi-agent discussion. Plan #35's within-round barrier/anonymization is the stronger replacement for preserving independent turns before exposure to peers. |
| Structured turn history | `DebateTurn` stored `round`, `side`, `argument`, `position`, and `timestamp`; a queue-like store preserved debate history for the judge. | Durable per-turn records let later reviewers audit who said what, when, and under which role. | `deliberate-task` artifacts should preserve turn-level records. `review-cycle` artifacts preserve review/apply rounds, which are not the same as pro/con turns. |
| Moderator setup artifact | `DebateSetup` split a user topic into `proposition`, `pro_position`, and `con_position`. | The setup stage makes the disagreement explicit before agents argue, reducing accidental cross-purpose responses. | Existing review profiles express role and objective in prompt data. If `deliberate-task` needs stronger debate setup, it should add a typed setup artifact there rather than depending on this generated agent. |
| Judge / synthesis artifact shape | `JudgmentOutput` contained `pro_score`, `con_score`, `rebuttal_quality`, `winner`, and `summary`; low combined score could request one more round. | Synthesis should be a separate adjudication step instead of being smeared into each debater's turn. | Plan #34 verifier/adjudicator ledgers and `AdversarialReview` verdicts are the canonical adjudication surfaces. Numeric debate scores are not reused unless a frozen `prompt_eval` metric proves they improve selection or calibration. |
| Schema compliance reporting | The generated runner counted schema violations from simple field/type checks and emitted a `schema_compliance` metric in `trace.json`. | Schema failures are first-class run quality signals and should not be buried in logs. | `llm_client` uses strict schema generation, permissive parse-normalization where needed, and explicit tests for live-boundary normalization. Schema compliance should be reported through observability and terminal artifacts, not a bespoke trace file. |
| Trace and execution metrics | `TRACE` captured agent label, model, prompts, responses, and duration; `dump_trace` summarized call count, latency, rough token estimates, clean exit, and agents used. | Multi-agent runs need inspectable traces for cost, latency, and failure diagnosis. | `llm_client` observability records actual call metadata and costs. `review-cycle` writes `budget_ledger.json` and `signoff.json`; OpenClaw links artifact paths. Rough token estimates from prompt length are not preserved. |
| Evaluation metrics not already covered | The legacy debate runner exposed winner, rebuttal quality, schema compliance, iteration count, clean exit, and rough token estimates. | These are potentially useful for debate-specific evaluation, but they do not replace artifact-review correctness metrics. | `prompt_eval` owns frozen comparisons. Debate-specific metrics can be added there after case sets exist; `AdversarialReview` should stay focused on artifact defects, contract violations, nits, and uncertainty. |

## Ideas Not Preserved as Runtime Code

- Direct provider calls, OpenRouter model mapping, retry fallbacks, and stub JSON
  fallback responses are replaced by `llm_client` provider routing and
  fail-loud behavior.
- Hand-written schema dictionaries and string JSON instructions are replaced by
  Pydantic contracts and JSON Schema response formats.
- The generated process graph is not reused. It mixes orchestration, provider
  calls, schemas, persistence, and console output in one file.
- Numeric pro/con scoring is not adopted as a general review-quality signal.
  It may be evaluated later in `prompt_eval`, but it is not a runtime gate for
  methodology whitepaper review.

## Archive Decision

`agents/debate_agent.py` is preserved as design prior art only. Its useful
topology and trace ideas are mapped to `deliberate-task`, Plan #34
adjudication, Plan #35 barrier/anonymization, `review-cycle` artifacts, and
`prompt_eval` evaluation. The remaining generated runnable path is duplicate
legacy infrastructure and should be tombstoned in the sibling repo or moved to
`~/projects/PROJECTS_DEFERRED/intermodel-dialogue-legacy/` only after sibling
repo safety checks.

