# Context for adversarial review

## What was being attempted

The Plan #35 within-round barrier protocol changed _make_agent_position_node
to read peer state from prior_positions_by_agent (round-(N-1) snapshot)
instead of latest_positions (round-N freshest, which leaked the cascade).

This commit fixes a follow-on interaction bug: the verifier's
_lineage_entries fabricated_peer_ref detector was still reading peer state
from latest_positions[peer]. Under the barrier, agents legitimately
reference the peer's round-(N-1) claim_ids (which they actually saw), but
the verifier compared those references against the peer's renamed round-N
claim_ids and flagged real references as fabricated.

## What changed

In llm_client/workflow/deliberate_verifier.py, verify_round() now passes
peer_prior to _lineage_entries based on round_num:
- peer_name is None → no peer (degenerate 1-agent case)
- round_num == 1 → empty position dict (peer hasn't written yet; any
  reference is fabricated)
- round_num >= 2 → prior_positions_by_agent.get(peer_name) (or empty
  position if missing — defensive)

## Adversarial review focus

Look for:
- Edge cases where the round_num == 1 vs round_num >= 2 dispatch is wrong
- Defensive empty-position fallback masking real fabrications (e.g., peer
  has a prior position but we pass {} instead)
- Coupling with the lineage detector that we didn't fix in tandem
  (silent_rename detection, silent_retire detection — do these still use
  the right comparison surface?)
- Whether the existing test coverage actually catches the false-positive
  regression
