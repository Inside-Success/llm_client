"""Retro-verify v3 positions with the post-fix verifier (Plan #35-aware).

The v3 run produced its live verifier_ledger.json with the verifier code as of
process startup. The post-run fix to _lineage_entries makes fabricated_peer_ref
read from prior_positions_by_agent instead of latest_positions (avoiding false
positives when peers rename claim_ids between rounds). This script rebuilds
the v3 ledger with the fixed code.

Usage::

    python scripts/meta/retro_verify_v3.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from llm_client.workflow.deliberate_verifier import VerifierLedger, verify_round

WORKSPACE = Path("/home/brian/brian-work-next/repos/llm_client_worktrees/plan-29-duet")
RUN_DIR = WORKSPACE / "runs" / "plan-35-barrier-pilot" / "v3"


def _load_if_exists(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def main() -> None:
    ledger = VerifierLedger()
    prior_by_agent: dict[str, dict] = {}
    for round_num in (1, 2, 3):
        latest: dict[str, dict] = {}
        for agent in ("agent_a", "agent_b"):
            p = RUN_DIR / f"position_{agent}_round_{round_num}.json"
            pos = _load_if_exists(p)
            if pos is not None:
                latest[agent] = pos  # type: ignore[assignment]
        if not latest:
            print(f"round {round_num}: no positions on disk — stopping")
            break
        if len(latest) < 2:
            print(f"round {round_num}: only {len(latest)} positions on disk — skipping")
            prior_by_agent = {**prior_by_agent, **latest}
            continue
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
        lineage = Counter(e.lineage_flag for e in round_entries if e.lineage_flag)
        print(f"round {round_num}: n={len(round_entries)} {dict(statuses)} lineage={dict(lineage)}")

    print()
    print(f"total ledger entries: {len(ledger.entries)}")
    print(f"  by status: {dict(Counter(e.status for e in ledger.entries))}")
    print(f"  by lineage: {dict(Counter(e.lineage_flag for e in ledger.entries if e.lineage_flag))}")

    out = RUN_DIR / "retro_verifier_ledger_post_fix.json"
    out.write_text(json.dumps([e.__dict__ for e in ledger.entries], indent=2))
    print()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
