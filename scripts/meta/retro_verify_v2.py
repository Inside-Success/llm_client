"""Retroactively re-run verifier on v2 positions with the improved parser.

The v2 deliberation was launched before the comma-range parser fix
(commit 6cd4c49). This script re-walks the v2 positions with the new
parser to quantify how much the fix improves the unparseable rate.

Usage::

    python scripts/meta/retro_verify_v2.py [--round N]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from llm_client.workflow.deliberate_verifier import VerifierLedger, verify_round

WORKSPACE = Path("/home/brian/brian-work-next/repos/llm_client_worktrees/plan-29-duet")
RUN_DIR = WORKSPACE / "runs" / "plan-33-self-deliberation-v2"


def _load_if_exists(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-round", type=int, default=3)
    args = parser.parse_args()

    ledger = VerifierLedger()
    prior_by_agent: dict[str, dict] = {}
    for round_num in range(1, args.max_round + 1):
        latest = {}
        for agent in ("agent_a", "agent_b"):
            p = RUN_DIR / f"position_{agent}_round_{round_num}.json"
            pos = _load_if_exists(p)
            if pos is not None:
                latest[agent] = pos
        if not latest:
            print(f"round {round_num}: no positions on disk yet — stopping")
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

    out = RUN_DIR / "retro_verifier_ledger_with_parser_fix.json"
    out.write_text(json.dumps([e.__dict__ for e in ledger.entries], indent=2))
    print()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
