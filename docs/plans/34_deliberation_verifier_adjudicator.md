# Plan #34: Deliberation Verifier / Adjudicator Stage

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #33 (deliberation chassis must exist before a verifier can attach to it)
**Blocks:** Long-running deliberation (>5 rounds reliability), DeliberationFamily extension point

---

## Gap

**Current:** The deliberation chassis (Plan #33) drives convergence from agents' **self-reported** metadata: `agreed_with_peer: list[str]` and `disagreed_with_peer: list[DisagreementAtom]`. `detect_convergence()` checks set-subset semantics on free-text strings. Findings carry `evidence_path: str` with no sub-grammar — `'docs/x.md#sec'`, `'file.py:LL-LL'`, and `'because I said so'` all pass schema validation. Nothing opens the cited file, resolves the line range, or checks that the snippet supports the claim.

**Evidence:** The deliberation just dogfood-reviewed itself (`runs/plan-33-self-deliberation/`). Both `codex/gpt-5.4` and `claude-code/opus` independently converged across 3 rounds on the same diagnosis (`synthesis.json:s1-s3`):
- s1: highest-priority next improvement is a chassis-owned verifier/adjudicator stage
- s2: convergence detector is structurally weaker than "polite agents trust" — agents can rename, retire, or fabricate peer claim IDs
- s3: `evidence_path` is unfalsifiable bare-string; even filesystem-only verification is insufficient (agent can cite a real `file:LL-LL` with misstated content)

**Target:** A non-LLM verifier pass that runs after each round, before `convergence_check`, and:
- Opens every claim's `evidence_path`, resolves it to `file_path + optional_line_range`, attaches the actual content snippet (5 lines around the cited range)
- Records per-claim status ∈ `{verified, unresolved_path, unparseable_evidence, file_not_found, content_mismatch_warning}`
- Tracks claim lineage across rounds: detects silent rename (same content, different `claim_id`), silent retire (`claim_id` present in round N, absent in round N+1 without explicit acknowledgment), fabricated peer reference (`agreed_with_peer` or `disagreed_with_peer.peer_claim_id` references an ID that doesn't exist in the peer's actual position)
- `detect_convergence()` consumes the ledger output rather than agents' self-reported `agreed_with_peer` / `disagreed_with_peer`

Stays pure-Python — no LLM in the verifier path. Preserves the rule-based determinism that's the convergence detector's reason for being.

---

## References Reviewed

- `runs/plan-33-self-deliberation/synthesis.json` — manual synthesis from the deliberation that produced this plan. Both agents converged on the verifier/adjudicator as #1 by round 3.
- `runs/plan-33-self-deliberation/position_agent_a_round_3.json`, `position_agent_b_round_3.json` — final positions with full file:line citations for each finding.
- `llm_client/workflow/deliberate.py:217-280` — current `detect_convergence` implementation. The convergence rule is `(round >= 2) AND (every agent has disagreed_with_peer == []) AND (every agent's agreed_with_peer covers peer's claim IDs)`. All three predicates trust agent self-reports.
- `llm_client/workflow/deliberate.py:95-138` — `PositionClaim` and `DisagreementAtom` schemas with `evidence_path: str`. No sub-grammar, no validator beyond non-empty string.
- `llm_client/workflow/deliberate.py:431-476, 683-693` — sequential `agent_a → agent_b` round topology that creates the round-1 non-independence issue (deliberation finding s4). Verifier doesn't fix this directly but can surface it: a round-1 position from agent_b that references agent_a's claims should be flagged.
- `llm_client/workflow/profiles/plan_doc_review.py:59-61` — existing `CitationRef(cited_as: str, reason_unverified: str)` shape in the duet's plan_doc_review profile. The verifier can borrow this shape for its per-claim ledger entries.
- `llm_client/execution/call_contracts.py:136-145` — `_check_budget(trace_id, max_budget)` already does cumulative-per-trace_id enforcement (counter to the deliberation's recanted s7). Verifier shouldn't add a parallel budget mechanism.

---

## Files Affected

- `llm_client/workflow/deliberate_verifier.py` (create) — `VerifierLedger`, `LedgerEntry`, `verify_position`, `verify_round`, claim-lineage tracker.
- `llm_client/workflow/deliberate.py` (modify) — `detect_convergence()` accepts the ledger as second arg; signature change. New `_make_verifier_node()` runs between agent_b's position write and `round_increment`. State carries `verifier_ledger: list[dict]`.
- `tests/test_workflow_deliberate_verifier.py` (create) — verifier covers: file resolution (resolved/unresolved), line-range parsing (parseable/unparseable), content snippet attachment, silent rename detection, silent retire detection, fabricated peer reference detection.
- `tests/test_workflow_deliberate.py` (modify) — update `test_convergence_detector_*` and `test_round_*` tests to thread the new ledger arg; one new test that ledger-based convergence fires when agents agree AND citations resolve, and fires-as-warning when agents agree BUT citations don't resolve.
- `docs/plans/34_deliberation_verifier_adjudicator.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append index row.

Out of scope (deliberately):
- LLM-semantic content match (does the cited snippet actually support the claim). Filesystem + snippet attachment is the v1 floor; semantic match is v2 if needed.
- `DeliberationFamily` registry (full TaskFamily parity for deliberation). Verifier MUST include a `verifier_hook` override point so a future profile can plug in domain-specific verification logic, but the full registry surface waits until evidence demands it.
- Verifier coverage for the duet's reviewer schemas (`PlanReviewBlocker.evidence_path`, `CorrectnessFinding.file_path+line`). The duet's `CorrectnessFinding` already has typed `file_path: str` and `line: int` fields. Worth a separate pass.
- Parallel agent execution / round-1 independence fix (deliberation finding s4). Separate change. Verifier can flag round-1 cross-agent references but doesn't restructure the topology.
- Synthesis context-bloat truncation (deliberation finding s5). Separate change.
- Cumulative budget ledger across runs (turns out it already works correctly per recanted s7).

---

## Plan

### Steps

1. `deliberate_verifier.py`: `LedgerEntry(claim_id, agent_name, round, evidence_path, status: Literal[...], file_path: Optional[str], line_range: Optional[tuple[int,int]], snippet: Optional[str], notes: str)`. `VerifierLedger` is `list[LedgerEntry]` with helper methods `entries_for_claim(claim_id, agent_name)`, `latest_status_for(claim_id)`, `lineage_for_round(round_num)`.
2. `verify_position(position: dict, workspace_path: str) -> list[LedgerEntry]`: for each claim in `position.claims`, parse `evidence_path` into one or more `file_path[:line_range]` references (split on `;`); for each, attempt resolution. Records `verified` only when the file exists AND the line range parses AND the range is within file length. Attaches a 5-line snippet centered on the cited range. Same for `position.disagreed_with_peer[*].evidence_path`.
3. `verify_round(latest_positions: dict[str, dict], prior_ledger: VerifierLedger, round_num: int, workspace_path: str) -> VerifierLedger`: extends the prior ledger with this round's entries plus lineage checks: (a) `silent_rename` — same `claim` string, different `claim_id` between rounds; (b) `silent_retire` — `claim_id` present in round N-1 absent in round N without acknowledgment; (c) `fabricated_peer_ref` — `agreed_with_peer` or `disagreed_with_peer[*].peer_claim_id` references an ID that doesn't exist in the peer's actual position at the relevant round.
4. `detect_convergence` signature change: `detect_convergence(latest_positions, round_num, max_rounds, ledger: VerifierLedger | None = None) -> DeliberationVerdict | None`. When ledger is provided: (a) refuse to fire `converged` if any agent's most recent claims have ledger entries with status != `verified`; (b) refuse `converged` if any lineage check (`silent_rename`, `silent_retire`, `fabricated_peer_ref`) is positive in the most recent round; (c) when ledger is None, fall back to today's behavior so the tests-without-ledger still work during migration.
5. `_make_verifier_node()`: a LangGraph node that runs after each `round_increment` (i.e. after both agents have spoken in a round). Reads `state["latest_positions"]` and `state["verifier_ledger"]`, calls `verify_round`, writes back the extended ledger. Returns updated state. No LLM call.
6. `build_deliberation_workflow` graph: insert `verifier` between `round_increment` and the conditional `post_round_router`. Router now consumes the ledger via the state field.
7. Persist `verifier_ledger.json` to `run_dir` alongside `signoff.json` so consumers of a finished run can inspect the per-claim verification trace.
8. Tests: see Required Tests table.
9. Optional `--verifier off` CLI flag on `deliberate-task` so callers can opt out (e.g. when iterating prompts and verification noise isn't helpful).
10. Plan index update.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_deliberate_verifier.py` | `test_verify_position_resolved_file_line` | A claim with `evidence_path = "foo.py:10-15"` against a real workspace file resolves; ledger entry has `status="verified"` and a non-empty `snippet`. |
| `tests/test_workflow_deliberate_verifier.py` | `test_verify_position_file_not_found` | `evidence_path = "nonexistent.py:1"` records `status="file_not_found"`, no snippet. |
| `tests/test_workflow_deliberate_verifier.py` | `test_verify_position_unparseable_evidence` | `evidence_path = "because I said so"` records `status="unparseable_evidence"`. |
| `tests/test_workflow_deliberate_verifier.py` | `test_verify_position_line_out_of_range` | Cited line range exceeds file length → `status="unresolved_path"` with the actual file length in `notes`. |
| `tests/test_workflow_deliberate_verifier.py` | `test_lineage_detects_silent_rename` | Round N has claim_id `a1` with content "X"; round N+1 has claim_id `a1_revised` with same content. Lineage check flags it as `silent_rename`. |
| `tests/test_workflow_deliberate_verifier.py` | `test_lineage_detects_silent_retire` | Round N has claim_id `a3`; round N+1 omits it without acknowledgment. Flagged as `silent_retire`. |
| `tests/test_workflow_deliberate_verifier.py` | `test_lineage_detects_fabricated_peer_ref` | `agreed_with_peer=["b99"]` where peer position has no claim with `claim_id="b99"`. Flagged as `fabricated_peer_ref`. |
| `tests/test_workflow_deliberate.py` | `test_convergence_refused_when_ledger_has_unverified_claims` | Even with empty `disagreed_with_peer` and complete `agreed_with_peer`, ledger entries with non-`verified` status block the `converged` verdict. |
| `tests/test_workflow_deliberate.py` | `test_convergence_refused_when_lineage_flag_in_latest_round` | A `fabricated_peer_ref` in the most recent round blocks `converged`. |
| `tests/test_workflow_deliberate.py` | `test_verifier_ledger_persisted_to_run_dir` | After a stubbed run, `verifier_ledger.json` exists in `run_dir`. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_deliberate.py::*` (existing) | Convergence semantics changed; existing tests must be updated to either pass a ledger explicitly or rely on the `ledger=None` backward-compat path. |
| `tests/test_workflow_schema_smoke.py` | Schemas unchanged; smoke must still pass live. |
| `tests/test_workflow_duet.py::*` | Duet path untouched. |

---

## Acceptance Criteria

- [ ] `pytest tests/test_workflow_deliberate_verifier.py tests/test_workflow_deliberate.py tests/test_workflow_schema_smoke.py tests/test_workflow_duet.py tests/test_workflow_profiles.py tests/test_cli_deliberate.py tests/test_cli_duet.py tests/test_cli_smoke.py -q` exits 0.
- [ ] A deliberation run with `--max-rounds 4` against the same task as `runs/plan-33-self-deliberation/` writes `verifier_ledger.json` alongside `signoff.json`; the ledger contains a `verified` entry for at least the citations in `position_agent_a_round_3.json` claim `a1` (`deliberate.py:217-280`, which definitely exists in the workspace).
- [ ] `detect_convergence(latest_positions, round_num, max_rounds, ledger)` refuses `converged` when ledger has any unverified entries OR any lineage flag in the most recent round.
- [ ] Backward compat: `detect_convergence(latest_positions, round_num, max_rounds)` (no ledger arg) preserves today's behavior.
- [ ] Verifier is pure-Python — no LLM calls, no network, no observability DB writes. Determinism is the point.

---

## Notes

**Design decisions**

- **Filesystem + snippet attachment as v1, LLM semantic match deferred.** The deliberation's own residual disagreement (a vs. b on whether syntactic verification is "enough") resolved as: filesystem alone is insufficient (agent can cite a real file:line with misstated content), but snippet attachment is enough for v1 because a human or downstream consumer can read the snippet and judge whether it supports the claim. LLM-semantic match becomes Plan #35 if needed.
- **Verifier is pure-Python, no LLM.** The convergence detector's reason for existing is determinism; an LLM-judge convergence detector is a different design (sketched in Plan #33 Notes as future, still future). Keep the layers distinct.
- **Ledger as a side-channel, not a replacement.** `agreed_with_peer` / `disagreed_with_peer` stay on the Position — they're useful for the synthesis prompt and for human consumers. The verifier ledger is the SOURCE OF TRUTH for `detect_convergence` but the agent self-reports remain visible.
- **Lineage tracking uses claim CONTENT, not claim_id.** Same-claim-different-id is the silent-rename signature; same-id-different-content is a different (less-common) drift mode that v1 can ignore.
- **Verifier shipped before full `DeliberationFamily` registry.** Per the deliberation's round-3 narrowing of b4: include an override hook (`verifier_hook: Callable[[Position, str], list[LedgerEntry]] | None`) on the workflow builder so a future profile can plug in domain-specific verification (e.g. PCM-layer-aware verification for twin_update). Don't ship the full registry until a second deliberation profile actually wants it.

**Risks**

- **Verifier false-positives** — `silent_retire` might fire when an agent legitimately abandons a claim because peer convinced them. Mitigation: require an explicit `acknowledged_retire` field on Position that the agent can populate to suppress the flag. v2 question.
- **`evidence_path` parsing brittleness.** Agents emit `"file.py:LL-LL; other_file.py#section; doc.md:42"` — multi-citation strings with mixed delimiters. v1 splits on `;` and tries `file:line[-line]` and bare-`file#section` parsers; complex citations get `unparseable_evidence`. Acceptable for v1.
- **Workspace path mismatch.** Verifier resolves paths relative to `task.workspace_path`. If agents cite paths that ARE inside the workspace but use absolute paths (or vice versa), the resolution can miss. Mitigation: try both relative-to-workspace AND absolute interpretations; record which one resolved.
- **Performance.** A 5-round deliberation with ~6 claims per agent per round = 60 ledger entries, each requiring a file read. File I/O is cheap; this isn't a real concern unless the workspace itself is on a slow filesystem.

**Follow-ups not in scope (queued for future plans)**

- LLM-semantic match: does the cited snippet actually support the claim? Plan #35 if needed.
- `DeliberationFamily` full registry parity with `TaskFamily`. Plan #36 if a domain profile demands it.
- Parallel agent execution per round (fixes round-1 non-independence). Plan #37.
- Synthesis context-bloat fix (truncation / summarization). Plan #38.
- Streaming round-by-round CLI output. Plan #39.
- Verifier coverage extended to duet's reviewer schemas.
