# Plan #35: Within-Round Barrier Protocol + Anonymization for Deliberation

**Status:** Blocked (Phases 1-4 shipped; optional Phase 6 requires a new decision)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Future deliberation protocol work

---

## Gap

**Current:** The deliberation chassis (`llm_client/workflow/deliberate.py`) wires `agent_a → agent_b → verifier → round_increment` on every round. Both agents read `latest_positions[peer_name]` at call time, so `agent_b` on round N sees `agent_a`'s freshest round-N output before generating its own round-N position. This is a **same-round second-mover advantage every round**, not a round-1 artifact. The convergence detector reads same-round `agreed_with_peer` (deliberate.py:280-289), so the bias propagates directly into the verdict.

**Target:** A Within-Round (WR) barrier protocol: in round N, both agents read only round-(N-1) snapshot state, generate round-N outputs in parallel-or-snapshot-equivalent, and the chassis commits both atomically before either reads peer state for round N+1. Combined with prompt-level anonymization ("Argument 1" / "Argument 2" instead of "agent_a said") and per-round turn-shuffle. Optional symmetric-replay on the final round before the verifier records the verdict.

**Why:** Plan #33's first real-task self-deliberation and Plan #34's v2 re-run both surfaced second-mover accommodation as a systemic effect. Both agents (codex/gpt-5.4 and claude-code/opus) independently converged in round 2 of v2 that the topology is the next-priority structural fix. The literature has settled on this fix — see References below — and the strongest cited result (Anonymization paper 2025) shows a **0.608 → 0.024 conformity-obstinacy gap reduction on MMLU** from prompt-level anonymization alone, a cheap intervention with the largest single bias-reduction number in the surveyed papers.

---

## References Reviewed

### Code

- `llm_client/workflow/deliberate.py:466-511` — `_make_agent_position_node` reads `latest.get(peer_name)` at call time
- `llm_client/workflow/deliberate.py:280-294` — convergence detector uses same-round `agreed_with_peer` subset rule
- `llm_client/workflow/deliberate.py:765-795` — `build_deliberation_workflow` edges: `agent_a → agent_b → verifier`
- `llm_client/workflow/deliberate.py:585-606` — `_synthesis_prompt` builds from `position_history`
- `llm_client/workflow/deliberate_verifier.py:533-580` — verifier consumes `latest_positions` per round; ledger is write-only to the router (Plan #34 known gap)
- `runs/plan-33-self-deliberation-v2/synthesis.json` — agent_a + agent_b round-2 convergence on the barrier-topology priority

### SOTA literature scan (Plan #35 commission, 2026-05-22)

| Citation | Result | Relevance |
|----------|--------|-----------|
| Du, Li, Torralba, Tenenbaum, Mordatch — "Improving Factuality and Reasoning in Language Models through Multiagent Debate" (2023) — [arXiv:2305.14325](https://arxiv.org/abs/2305.14325) | Canonical multi-agent debate protocol: each agent conditions on prior-round responses from all other agents (parallel reveal). | Defines the WR baseline we're adopting. |
| "The impact of multi-agent debate protocols on debate quality: a controlled case study" (2026) — [arXiv:2603.28813](https://arxiv.org/html/2603.28813v1) | Within-Round (WR) vs Cross-Round (CR) head-to-head. Peer-Reference Rate: WR 0.320 > CR 0.282. Consensus: RA-CR 0.647 ≫ CR 0.359 (p<0.001). **Both WR and CR shuffle agent-turn order as baseline hygiene.** | Direct comparison; informs the WR vs CR tradeoff and confirms turn-shuffle is non-optional. |
| "Measuring and Mitigating Identity Bias in Multi-Agent Debate via Anonymization" (2025) — [arXiv:2510.07517](https://arxiv.org/html/2510.07517v1) | Qwen-32B on MMLU: conformity-obstinacy gap drops 0.608 → 0.024. Identity Bias Coefficient drops 0.22–0.58 across 20 conditions. | Largest single bias-reduction number in the scan, on the cheapest intervention (prompt-level anonymization). |
| Irving, Christiano, Amodei — "AI Safety via Debate" (2018) — [arXiv:1805.00899](https://arxiv.org/abs/1805.00899) | Gold-standard symmetric counterbalancing: play two debates with swapped order; cost 2× compute. | Reserved for verifier final round only. |
| Zheng et al. — "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (2023) — [arXiv:2306.05685](https://arxiv.org/abs/2306.05685) | GPT-4 flips its verdict on ~1/3 of pairwise judgments when order is swapped. | Order bias is well-documented in pairwise judgments. Motivates the symmetric-replay-on-final-round option. |
| "Talk Isn't Always Cheap: Failure Modes in Multi-Agent Debate" (2025) — [arXiv:2509.05396](https://arxiv.org/html/2509.05396v1) | Debate can *degrade* a stronger agent's accuracy when paired with a weaker one — 65.8% → 58.8% on MMLU. | **Risk for our claude-opus + codex-gpt-5.4 pairing.** Plan must include an asymmetric-agent A/B check. |
| Liang et al. — "Encouraging Divergent Thinking in LLMs through Multi-Agent Debate" (EMNLP 2024) — [arXiv:2305.19118](https://arxiv.org/abs/2305.19118), [code](https://github.com/Skytliang/Multi-Agents-Debate) | Tit-for-tat debate with a third-agent judge; reference implementation available. | Judge-mediated alternative; not our chosen path (the judge becomes the position-bias surface) but worth knowing as an alternative. |

---

## Files Affected

- `llm_client/workflow/deliberate.py` (modify): add `previous_round_positions` to `DeliberationState`; change `_make_agent_position_node` to read from the snapshot, not `latest_positions`; add `round_snapshot` node that publishes the snapshot at round start; update `build_deliberation_workflow` edges.
- `llm_client/workflow/deliberate.py` (modify): `_position_prompt` to anonymize peer references — replace "your peer agent_a said …" with "Argument 1: …" / "Argument 2: …" with per-round shuffle.
- `llm_client/workflow/deliberate.py` (modify): per-round turn-shuffle seed (deterministic from `round_num` so runs are reproducible).
- `tests/test_workflow_deliberate.py` (modify): add tests for barrier semantics — verify round-N agents see only round-(N-1) snapshot.
- `tests/test_workflow_deliberate_barrier.py` (create): focused barrier-protocol unit tests; anonymization tests; turn-shuffle tests.
- `runs/plan-35-barrier-pilot/` (artifact dir, created at run time): A/B comparison artifacts vs the cascade-topology baseline.
- `docs/plans/CLAUDE.md` (modify): add Plan #35 row to the index.
- `docs/plans/34_deliberation_verifier_adjudicator.md` (modify): note that the Plan #35 follow-up was reordered (barrier first, LLM-semantic match second).

---

## Plan

### Phase 1 — Barrier semantics (chassis change)

1. Add `previous_round_positions: dict[str, dict] | None` field to `DeliberationState` schema.
2. Add `_make_round_snapshot_node` that copies `latest_positions` → `previous_round_positions` at round start (entry point of each round, before either agent runs).
3. Change `_make_agent_position_node` to read `state["previous_round_positions"]` instead of `state["latest_positions"]` for peer state. Own prior still comes from `latest_positions` (an agent is allowed to see its own most-recent output; the symmetry concern is about peer state).
4. Update `build_deliberation_workflow` edges: `round_snapshot → agent_a → agent_b → verifier → round_increment` (still sequential for now; LangGraph parallel-branch is Phase 4 if A/B shows it's needed).
5. Round 1 special case: `previous_round_positions` is empty/None on round 1, so agents have no peer state to read. Matches the v1 behavior already documented in `_position_prompt`.

### Phase 2 — Anonymization

6. Modify `_position_prompt` to replace named peer references with "Argument 1" / "Argument 2" labels. Per-round shuffle so "Argument 1" doesn't consistently mean the same model.
7. The mapping (which label maps to which agent) is recorded in state for the verifier and synthesis stages — they need the deanonymized view to track lineage and write the final verdict. Anonymization is prompt-only, not state-wide.
8. Deterministic shuffle seed: `hash((task_id, round_num))` so reruns are reproducible.

### Phase 3 — Test coverage

9. Unit tests in `tests/test_workflow_deliberate_barrier.py`:
   - barrier: round-2 agents see only round-1 positions, not round-2 peer's same-round output
   - barrier: round-1 agents see empty peer state
   - anonymization: prompt contains "Argument 1" / "Argument 2", not raw agent names
   - shuffle determinism: same (task_id, round_num) produces same label mapping
   - shuffle variety: across different round numbers, label-to-agent mapping changes
   - verifier still sees deanonymized state (lineage flags still fire correctly)
10. Update existing tests in `tests/test_workflow_deliberate.py` that assert on the old cascade behavior.
11. Full sweep: `pytest -q -k "workflow or deliberate"` must pass (modulo the 4 pre-existing prompt-asset failures unrelated to deliberate).

### Phase 4 — Empirical A/B (gates Phase 5)

12. Re-run the self-deliberation task (`runs/plan-33-self-deliberation/task.json`) once with barrier+anonymization (Plan #35 chassis) and once with the cascade baseline (Plan #34 chassis). Same agents, same max_rounds=3, same workspace.
13. Compare: verdict (converged / productive_disagreement), round count, agreed_with_peer overlap, claim turnover between rounds (silent_rename / silent_retire counts from the verifier), and synthesis quality.
14. Specifically instrument: does the barrier produce more independent round-1 positions than the cascade? Does round-2 convergence shift?
15. Document the A/B in `runs/plan-35-barrier-pilot/comparison.md` with the raw artifacts.

### Phase 5 — Symmetric replay (conditional)

16. **Only if Phase 4 shows the barrier still produces order-sensitive verdicts** on the final round, add Irving-style symmetric replay: re-run final round with positions swapped and require the verifier to agree on both orderings before signoff. Costs +1 LLM call per debate. Default off; opt-in via `--symmetric-final` CLI flag.
17. Skip this phase entirely if Phase 4 confirms the barrier alone is sufficient (which is the literature's prediction — Du et al. and 2603.28813 both treat WR as the standalone fix).

### Phase 6 — Asymmetric-agent risk check

18. Per "Talk Isn't Always Cheap" (arXiv:2509.05396): debate can degrade a stronger model paired with a weaker one. Our claude-code/opus + codex/gpt-5.4 pairing has unknown asymmetry.
19. Run a small benchmark: each agent solo on a sample of the same review tasks vs. paired-debate (post-Phase-4 barrier chassis) on the same tasks. Compare final accuracy/quality.
20. If solo > paired-debate for the stronger agent: document the asymmetry boundary, recommend a model-pairing policy, do NOT silently keep debate enabled. This is a stop-and-decide point, not autonomous-implementable.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_deliberate_barrier.py` | `test_round_2_agents_see_only_round_1_snapshot` | Barrier semantics: round-2 agents read previous_round_positions, not latest_positions |
| `tests/test_workflow_deliberate_barrier.py` | `test_round_1_agents_see_empty_peer_state` | Round 1 baseline |
| `tests/test_workflow_deliberate_barrier.py` | `test_round_snapshot_publishes_before_either_agent_runs` | Topology contract |
| `tests/test_workflow_deliberate_barrier.py` | `test_prompt_anonymizes_peer_reference` | "Argument 1" / "Argument 2" in prompt, not raw agent names |
| `tests/test_workflow_deliberate_barrier.py` | `test_shuffle_is_deterministic_per_task_and_round` | Same (task_id, round_num) → same label mapping |
| `tests/test_workflow_deliberate_barrier.py` | `test_shuffle_varies_across_rounds` | Label-to-agent mapping changes per round |
| `tests/test_workflow_deliberate_barrier.py` | `test_verifier_still_sees_deanonymized_state` | Lineage flags still fire correctly under anonymization |
| `tests/test_workflow_deliberate.py` | `test_existing_topology_assertions` | Update existing tests that assumed cascade topology |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_deliberate_verifier.py` | Plan #34 verifier semantics unchanged |
| `tests/test_workflow_deliberate.py` | Existing convergence / synthesis / signoff tests still pass |
| `tests/test_workflow_schema_smoke.py` (integration) | Live-LLM smoke tests still pass with new prompt shape |

---

## Acceptance Criteria

- [ ] Phase 1-3 tests pass
- [ ] Full workflow sweep passes (modulo 4 pre-existing prompt-asset failures unrelated to deliberate)
- [ ] Phase 4 A/B comparison artifacts committed under `runs/plan-35-barrier-pilot/`
- [ ] Phase 4 comparison shows barrier+anonymization produces measurable independence improvement (e.g., higher peer-reference rate, lower second-mover accommodation rate)
- [ ] Phase 6 asymmetric-agent check completed; recommendation documented even if "no change needed"
- [ ] `docs/plans/CLAUDE.md` updated to mark Plan #35 row
- [ ] API reference regenerated if public surface changed

---

## Notes

### Design decisions

- **Why barrier + anonymization together, not just barrier?** Because the literature's strongest single bias-reduction result (0.608 → 0.024 from arXiv:2510.07517) is from anonymization alone, and the cost is purely prompt-template. Adding it now means we don't ship a partial fix.

- **Why not parallel agent execution via LangGraph fan-out in Phase 1?** Sequential edges with snapshot-based reads achieve the same semantic guarantee (each agent sees only round-(N-1) peer state) with a smaller chassis change. If Phase 4 shows wall-clock is a bottleneck, Phase 4+ can convert to parallel branches without changing the protocol contract.

- **Why is symmetric-replay (Phase 5) conditional?** Du et al. and the 2026 controlled study both treat WR as the standalone fix. Irving 2018's symmetric-replay is the gold standard but 2× compute. The literature's prediction is that we won't need replay; Phase 4 tests that prediction.

- **Why is asymmetric-agent check (Phase 6) a stop-and-decide point?** "Talk Isn't Always Cheap" (arXiv:2509.05396) shows debate can hurt the stronger agent (65.8% → 58.8% on MMLU). If our pairing triggers that failure mode, the right answer might be "don't pair these two for debate" — a product decision Brian should weigh in on, not autonomous.

### Alternatives considered

- **Judge-mediated debate** (Liang et al., MAD): a third agent reads both positions and mediates. Rejected because it just moves the position-bias surface to the judge; doesn't fix the underlying symmetry problem.
- **Counterfactual stance presets** (CFMAD, arXiv:2406.11514): force one agent to argue one side, the other to argue the opposite. Rejected because our use case is collaborative analysis, not adversarial debate.
- **Always-symmetric (run all rounds twice with swapped order, average)**: matches Irving 2018 but 2× cost for every round. Reserved as Phase 5 conditional on Phase 4 results.
- **Ensemble-then-aggregate** (sample N independent positions, take consensus): more like self-consistency than debate. Loses the iterated-refinement mechanism we want.

### Risks

- **Anonymization may confuse models that rely on speaker identity for context.** The arXiv:2510.07517 result is on MMLU, not on technical-claim debate with file:line citations. Mitigation: Phase 4 A/B catches this.
- **Sequential-with-snapshot may not feel like a "barrier" to the LLM** if it can infer the cascade from the prompt structure. Mitigation: anonymization removes the cue; shuffle removes the position cue.
- **Plan #34 verifier-feedback gap still unfixed.** The verifier ledger is still write-only to the router. Plan #35 does not address this, by design — a fix on top of biased topology would just produce biased convergence faster. Plan #36 (or later) addresses verifier-feedback.

### Follow-ups (queued for future plans)

- **Plan #36** — verifier-feedback into `_position_prompt` and `_synthesis_prompt` (agents learn *why* convergence was refused).
- **Plan #37** — LLM-semantic content match (does the cited snippet actually support the claim) — was originally Plan #35 in the Plan #34 doc; reordered after v2 surfaced barrier as #1.
- **Plan #38** — N-agent generalization (currently chassis is hardcoded to 2 agents).
- **Plan #39** — model-pairing policy if Phase 6 surfaces a real asymmetry boundary.
