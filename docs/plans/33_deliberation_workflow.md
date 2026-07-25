# Plan #33: Deliberation Workflow (Symmetric N-Agent Debate)

**Status:** Complete (core workflow shipped; obsolete Opus default superseded)
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #31 (TaskFamily abstraction reused here)
**Blocks:** Future eval_audit profile (which may attach to either duet or deliberation depending on shape fit)

---

## Gap

**Current:** The duet workflow (Plans #29-32) is asymmetric: one agent implements, the other gates with `verdict ∈ {pass, revise, block}`. One revise cycle. That's the right shape when there's a plan to execute and a reviewer to check it. It is the **wrong** shape for what Brian actually does most often: hand a task or question to two coding agents (Codex + Claude Code), let each do independent investigation and form a position, then have them argue back and forth until they converge or hit explicit unresolved disagreement.

The manual workflow Brian's been doing by hand:
1. Give Codex a task → it investigates and produces analysis.
2. Paste Codex's output to Claude Code → "review this."
3. Paste Claude's response back to Codex → "respond."
4. Loop until convergence (or until Brian decides one side is right).

The duet's `plan_doc_review` profile can do step 2-3 once, but not the multi-round symmetric back-and-forth, and not the "each agent investigates independently first" framing.

**Target:** A sibling workflow `deliberate` that:
- **Symmetric.** Both agents get the same task. No implementer/reviewer roles.
- **Independent investigation round 1.** Each agent reads the task + workspace and writes its own `Position` (claims, evidence, open questions, confidence).
- **Argument rounds 2+.** Each agent reads the other's prior Position plus its own prior and emits a new Position that acknowledges agreed points, disagrees explicitly with cited evidence, and may revise its own claims.
- **Convergence detection.** A rule-based check after each round: agents agree (all claims acknowledged with no `disagrees_with_peer` entries) → terminal `converged`. Cycle cap exceeded with unresolved disagreement → terminal `productive_disagreement`. Both agents emit empty positions or fail to engage → terminal `stalled`.
- **Synthesis.** Final stage produces a merged finding + residual disagreements artifact.
- **Reuses the chassis.** TaskFamily, grounded schemas with `evidence_path`, CLI surface, artifact persistence, model alias resolution.

**Why:** The single-pass adversarial review pattern (`duet-review`) is one valid mode but doesn't replace the back-and-forth model. Many real questions don't have a "right answer" the reviewer can verdict on; they need two minds independently chewing on a problem and surfacing where they disagree. Without `deliberate`, Brian keeps doing this manually.

---

## References Reviewed

- `llm_client/workflow/duet.py:62-87` — `DuetTask` schema with `extra: dict[str, Any]`; reusable as `DeliberationTask`.
- `llm_client/workflow/duet_base.py:30-50` — `PlanReviewBase` / `ImplementReviewBase` pattern. The deliberation analog is `PositionBase` carrying `confidence` + `state ∈ {initial, revised, agreed, disagreed}` instead of `verdict`.
- `llm_client/workflow/duet.py:535-635` — node factory pattern; deliberation has only one node type (`agent_position_node`) plus a `convergence_check_node` and a `synthesis_node`. Much smaller than the duet's four asymmetric nodes.
- `llm_client/workflow/duet_registry.py:1-65` — TaskFamily registry. Deliberation profiles register against the same registry; the `task_family` resolution lookup is identical (registry doesn't know whether a family is duet-shaped or deliberation-shaped — that's determined by which builder consumes it).
- `llm_client/cli/duet.py:99-228` — established CLI subcommand pattern; `deliberate-task` mirrors the shape with `--agents` (comma-separated), `--max-rounds`, `--task-file` (task brief from file rather than CLI string).
- Existing duet self-review artifacts at `runs/plan-{29,30,31,32}-*-review/` — evidence that the single-pass review pattern works for plan critique. Deliberation is *not* a replacement for that — it's a different shape for different questions.

---

## Files Affected

- `llm_client/workflow/deliberate.py` (create) — chassis: schemas (Position, PositionClaim, PositionEvidence, DisagreementAtom, DeliberationSignoff), node factories (agent_position, convergence_check, synthesis), `build_deliberation_workflow()`.
- `llm_client/workflow/__init__.py` (modify) — export new types.
- `llm_client/cli/deliberate.py` (create) — `cmd_deliberate_task` + `register_parser` mirroring `cli/duet.py`.
- `llm_client/__main__.py` (modify) — register `deliberate-task` subcommand.
- `tests/test_workflow_deliberate.py` (create) — offline tests with stubbed agents: round-1 produces independent positions; round-2 reads peer position; convergence detector fires on agreement; cycle cap promotes to `productive_disagreement`; synthesis produces final artifact.
- `tests/test_cli_deliberate.py` (create) — CLI flag routing, --agents parsing, --max-rounds threading.
- `tests/test_cli_smoke.py` (modify) — extend smoke list with `deliberate-task --help`.
- `docs/plans/33_deliberation_workflow.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append index row; update the "Duet stack" section to mention the deliberation sibling.

Out of scope (deliberately):
- LLM-based convergence detection. Rule-based for v1 (cheap, predictable). LLM-judge layer can come later if rules prove brittle.
- N-agent (3+) topology in v1. Two-agent is the manual pattern Brian's doing today; symmetric N is a natural extension but more LangGraph wiring without proven need.
- Profile-specific positions. The `generic` profile carries `PositionBase`; domain profiles can subclass when there's evidence they need to.
- `--read-only` flag. Default to full workspace access (matches the manual flow where Codex actually edits/explores).
- Live integration tests against real `claude-code` / `codex`. Offline unit tests prove wiring; first dry-run is a separate slice.

---

## Plan

### Steps

1. `deliberate.py`: `DeliberationVerdict = Literal["converged", "productive_disagreement", "stalled"]`. `DeliberationTask(BaseModel)` with `task_id, title, question, workspace_path, success_criteria, constraints, extra` — mirrors DuetTask but reframes the goal as a question rather than a plan-to-implement.
2. `Position` schema: `agent_name: str`, `round: int`, `claims: list[PositionClaim]`, `evidence: list[PositionEvidence]`, `open_questions: list[str]`, `agreed_with_peer: list[str]` (claim IDs from peer's prior position), `disagreed_with_peer: list[DisagreementAtom]`, `confidence: Literal["low", "medium", "high"]`, `state: Literal["initial", "revised", "stable"]`, `reviewer_summary: str`.
3. `PositionClaim(claim_id, claim, severity, evidence_path)` — claims are atomic so peer can refer by `claim_id`. `evidence_path` required (groundedness rule from Plan #30).
4. `PositionEvidence(label, citation, content_snippet)` — explicit citations the agent pulls into its position; peer can scrutinize.
5. `DisagreementAtom(peer_claim_id, my_counterclaim, evidence_path)` — required `evidence_path` so disagreement is grounded.
6. `DeliberationSignoff(task_id, final_verdict, total_rounds, agents, residual_disagreements, trace_id, artifacts_index)`.
7. Node factories: `_make_agent_position_node(agent_model, agent_name, family)` produces a node that, given state, reads the task brief + the *other* agent's most-recent position (if any) + its own prior position (if any), and emits a new Position via `call_llm_structured`. `_make_convergence_check_node()` — pure-Python rule check, no LLM call: agents converged when (a) round ≥ 2 and (b) both latest positions have empty `disagreed_with_peer` lists and (c) each agent acknowledged each of the peer's claims. `_make_synthesis_node()` calls an LLM (configurable model; default the more "objective" agent or a third model) to produce a synthesis artifact summarizing merged findings + residual disagreements.
8. Router: after each round, run convergence_check; if `converged` → synthesis → signoff_pass; if `productive_disagreement` (cycle cap hit) → synthesis (still useful — surfaces what they couldn't agree on) → signoff_block; if `stalled` (both empty) → signoff_block.
9. `build_deliberation_workflow(run_dir, task, trace_id, max_budget, agents=[(name, model), ...], max_rounds=3, task_family="generic", checkpointer=None, synthesis_model=None)`. Two-agent default if `agents=None`: `[("agent_a", "codex/gpt-5.4"), ("agent_b", "claude-code/opus")]`.
10. Cycle topology in LangGraph: parallel two-agent step is a Send-pattern in LangGraph, or simpler: sequential agent_a → agent_b in each round so each sees the latest peer position (the conventional model for two-agent debate). v1 uses sequential; parallel is a refinement once we see real round shape.
11. `cli/deliberate.py`: `cmd_deliberate_task` reads `--task-file` (JSON or YAML), parses `--agents "agent_a:codex/gpt-5.4,agent_b:claude-code/opus"`, passes `--max-rounds`, optional `--task-family`, optional `--synthesis-model`. Writes per-round artifacts `position_<agent>_round_<N>.json` plus `synthesis.json` + `signoff.json`.
12. Public exports + CLI registration + smoke test entry.
13. Plan index update.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_deliberate.py` | `test_round_1_produces_independent_positions` | First round: both agents read task only, neither sees the other's output. |
| `tests/test_workflow_deliberate.py` | `test_round_2_reads_peer_prior_position` | Second round: each agent's prompt includes the peer's round-1 position. |
| `tests/test_workflow_deliberate.py` | `test_convergence_detector_fires_on_empty_disagreement_lists` | Rule: round ≥ 2 + both `disagreed_with_peer == []` + acknowledgments cover peer's claims → `converged`. |
| `tests/test_workflow_deliberate.py` | `test_cycle_cap_promotes_to_productive_disagreement` | Hit `max_rounds` with residual `disagreed_with_peer` → terminal `productive_disagreement`. |
| `tests/test_workflow_deliberate.py` | `test_stalled_when_both_agents_emit_empty_positions` | Both agents return positions with zero claims → terminal `stalled`. |
| `tests/test_workflow_deliberate.py` | `test_position_claim_requires_evidence_path` | Groundedness: schema rejects `PositionClaim` without `evidence_path`. |
| `tests/test_workflow_deliberate.py` | `test_disagreement_atom_requires_evidence_path` | Groundedness on the disagreement side too. |
| `tests/test_workflow_deliberate.py` | `test_synthesis_produces_residual_disagreements_list` | When verdict is `productive_disagreement`, synthesis artifact lists what they couldn't agree on. |
| `tests/test_workflow_deliberate.py` | `test_two_agent_default_uses_codex_and_claude_code` | When `agents=None`, defaults to codex/gpt-5.4 + claude-code/opus. |
| `tests/test_cli_deliberate.py` | `test_cli_parses_agents_flag` | `--agents "a:codex/gpt-5.4,b:claude-code/opus"` → `[("a", "codex/gpt-5.4"), ("b", "claude-code/opus")]`. |
| `tests/test_cli_deliberate.py` | `test_cli_default_task_family_is_generic` | Mirrors duet CLI default. |
| `tests/test_cli_deliberate.py` | `test_cli_threads_max_rounds_into_builder` | --max-rounds N reaches the builder kwarg. |
| `tests/test_cli_smoke.py` | `test_cli_help_smoke` | `deliberate-task --help` exits 0. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_duet.py` | Duet still works; deliberate is a sibling, not a replacement. |
| `tests/test_workflow_profiles.py` | TaskFamily registry shared between duet and deliberate. |
| `tests/test_cli_duet.py` | Duet CLI unchanged. |
| `tests/test_agents.py::TestWorkspaceKwargAliasing` | cwd aliasing applies to both workflows. |

---

## Acceptance Criteria

- [x] Full sweep `pytest tests/test_workflow_deliberate.py tests/test_workflow_duet.py tests/test_workflow_profiles.py tests/test_workflow_builder.py tests/test_workflow_context_config.py tests/test_agents.py::TestBuildAgentOptions tests/test_agents.py::TestWorkspaceKwargAliasing tests/test_cli_smoke.py tests/test_cli_duet.py tests/test_cli_deliberate.py -q` exits 0.
- [x] `python -m llm_client deliberate-task --help` exits 0 and prints `--agents`, `--max-rounds`, `--task-file`, `--task-family`, `--synthesis-model`.
- [x] Convergence detector is pure-Python (no LLM call) and deterministic for given inputs.
- [x] `PositionClaim` and `DisagreementAtom` both reject payloads missing `evidence_path` at Pydantic validation time.
- [x] The two-agent default is explicit. The original `claude-code/opus`
  criterion was superseded by the later Opus ban; the retained default uses
  `codex/gpt-5.4` and `claude-code/sonnet`.
- [x] Synthesis stage runs even on `productive_disagreement` — surfaces what wasn't resolved instead of suppressing it.

---

## Notes

**Design decisions**

- **Sequential per round, not parallel.** Two-agent debate typically wants each agent to see the latest peer position. Parallel (Send pattern in LangGraph) is a refinement once we have real round-shape evidence; sequential is the standard interpretation of the manual workflow.
- **Rule-based convergence, not LLM-judge.** A rule check (both `disagreed_with_peer == []` and acknowledgments covered) is cheap and predictable. LLM-judge convergence is appealing but adds a non-deterministic gate that's harder to reason about. Layer in later if rules prove too coarse.
- **`Position.state ∈ {initial, revised, stable}` not `{pass, revise, block}`.** Verdicts don't apply to deliberation — there's no gating, just stance evolution.
- **Synthesis runs even on `productive_disagreement`.** The whole point of deliberation is to surface what two minds genuinely disagree about. A "they disagreed" terminal that hides the disagreements would defeat the workflow.
- **Reuses `TaskFamily` registry.** The chassis-vs-profile split from Plan #31 applies to deliberation too. A `code_review_deliberation` profile could specialize the Position schema later. v1 ships only `generic`.
- **No verdict-based router on the deliberation side.** The duet's router checks `verdict`; deliberation's "router" is the convergence detector reading both latest positions. Different mechanism, same chassis position (LangGraph conditional edge).

**Risks**

- **Schema verbosity.** `Position` has more fields than the duet's `PlanReview`. Bigger structured-output payloads = higher LLM error rate on Pydantic validation. Mitigated by required `evidence_path` keeping the schema disciplined and by groundedness tests at validation time.
- **Convergence-detector false positives.** Two agents might emit empty `disagreed_with_peer` because they're being polite, not because they actually agree. Rule check is "necessary but not sufficient" for true convergence. Worth pairing with a "confidence ≥ medium" requirement on both sides, or downgrading `converged` to "apparent_agreement" until LLM-judge validates. v1 stays simple.
- **Sequential bias.** If agent_a always goes first, it anchors the framing. Mitigated by alternating which agent leads each round (round 1 a→b, round 2 b→a, etc.) — small wiring change, worth doing in v1.
- **Synthesis model choice.** Defaulting to one of the two debating agents introduces a meta-bias (the agent doing synthesis re-asserts its own position). Default `synthesis_model=None` → use a third model if one is configured, otherwise default to claude-code/opus (it's the more structured-output-disciplined model). This is a design call worth revisiting after first real runs.

**Follow-ups not in scope**

- LLM-judge convergence detection.
- N-agent (≥3) topology.
- Parallel-per-round Send pattern in LangGraph.
- Domain-specific deliberation profiles (e.g. `eval_design_deliberation`).
- Streaming positions (currently structured-output single-shot per round).
- Human-in-the-loop interrupt between rounds.
- A meta-duet that consumes deliberation `signoff.json` corpora.
