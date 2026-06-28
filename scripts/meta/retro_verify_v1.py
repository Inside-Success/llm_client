"""Retroactively run the Plan #34 verifier against the v1 deliberation positions.

Walks the six v1 positions in (round, agent) order and rebuilds the ledger as
if the verifier had been active during the run. Emits a compact status
breakdown so we can see whether the verifier would have caught bogus
citations in the run that motivated it.

Usage::

    python scripts/meta/retro_verify_v1.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from llm_client.workflow.deliberate_verifier import VerifierLedger, verify_round

WORKSPACE = Path("/home/brian/brian-work-next/repos/llm_client_worktrees/plan-29-duet")
RUN_DIR = WORKSPACE / "runs" / "plan-33-self-deliberation"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    positions: dict[int, dict[str, dict]] = {1: {}, 2: {}, 3: {}}
    for round_num in (1, 2, 3):
        for agent in ("agent_a", "agent_b"):
            p = RUN_DIR / f"position_{agent}_round_{round_num}.json"
            positions[round_num][agent] = _load(p)

    ledger = VerifierLedger()
    prior_by_agent: dict[str, dict] = {}
    for round_num in (1, 2, 3):
        latest = positions[round_num]
        ledger = verify_round(
            latest_positions=latest,
            prior_positions_by_agent=prior_by_agent,
            prior_ledger=ledger,
            round_num=round_num,
            workspace_path=str(WORKSPACE),
        )
        prior_by_agent = latest
        round_entries = [e for e in ledger.entries if e.round == round_num]
        statuses = Counter(e.status for e in round_entries)
        lineage = Counter(
            e.lineage_flag for e in round_entries if e.lineage_flag is not None
        )
        print(f"round {round_num}: {dict(statuses)} lineage={dict(lineage)}")

    print()
    print(f"total ledger entries: {len(ledger.entries)}")
    print(f"  by status: {dict(Counter(e.status for e in ledger.entries))}")
    print(f"  by lineage: {dict(Counter(e.lineage_flag for e in ledger.entries if e.lineage_flag))}")

    bad = [e for e in ledger.entries if e.status != "verified"]
    if bad:
        print()
        print(f"non-verified entries ({len(bad)}):")
        for e in bad[:20]:
            print(f"  {e.agent_name} r{e.round} {e.claim_id} status={e.status} ev={e.evidence_path!r} notes={e.notes}")

    out = RUN_DIR / "retro_verifier_ledger.json"
    out.write_text(json.dumps([e.__dict__ for e in ledger.entries], indent=2))
    print()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
