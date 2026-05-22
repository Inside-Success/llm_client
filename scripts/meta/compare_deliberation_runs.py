"""Compare deliberation runs across chassis revisions.

Reads on-disk artifacts from v1, v2, and v3 runs of the meta self-deliberation
and emits a side-by-side table on three axes:

1. Round-1 independence — do agents reference each other's claim_ids before
   any cross-talk should be possible? (Cascade leak indicator.)
2. Lineage drift — silent_retire and fabricated_peer_ref counts per round.
3. Convergence trajectory — verdict + round count + agreed_with_peer growth.

v1: runs/plan-33-self-deliberation/        (cascade, no verifier)
v2: runs/plan-33-self-deliberation-v2/     (cascade, verifier with old parser)
v3: runs/plan-35-barrier-pilot/v3/         (barrier+anon, verifier with new parser)

Usage::

    python scripts/meta/compare_deliberation_runs.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path("/home/brian/brian-work-next/repos/llm_client_worktrees/plan-29-duet")
RUNS = {
    "v1 cascade no-verifier": ROOT / "runs" / "plan-33-self-deliberation",
    "v2 cascade verifier": ROOT / "runs" / "plan-33-self-deliberation-v2",
    "v3 barrier+anon": ROOT / "runs" / "plan-35-barrier-pilot" / "v3",
}


def _load_if_exists(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _positions_for_round(run_dir: Path, round_num: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for agent in ("agent_a", "agent_b"):
        p = run_dir / f"position_{agent}_round_{round_num}.json"
        d = _load_if_exists(p)
        if d is not None:
            out[agent] = d  # type: ignore[assignment]
    return out


def _claim_ids(pos: dict) -> set[str]:
    return {c.get("claim_id") for c in (pos.get("claims") or []) if c.get("claim_id")}


def _disagreement_claim_id_refs(pos: dict) -> set[str]:
    return {d.get("peer_claim_id") for d in (pos.get("disagreed_with_peer") or []) if d.get("peer_claim_id")}


def analyze_run(label: str, run_dir: Path) -> dict:
    out: dict = {"label": label, "run_dir": str(run_dir.relative_to(ROOT))}

    signoff = _load_if_exists(run_dir / "signoff.json")
    if signoff:
        out["verdict"] = signoff.get("final_verdict")
        out["total_rounds"] = signoff.get("total_rounds")

    # Per-round analysis
    out["rounds"] = []
    for r in (1, 2, 3):
        positions = _positions_for_round(run_dir, r)
        if not positions:
            continue
        row = {"round": r}
        for agent_name, pos in positions.items():
            cid = _claim_ids(pos)
            agreed = set(pos.get("agreed_with_peer") or [])
            disagreed_refs = _disagreement_claim_id_refs(pos)
            row[f"{agent_name}_n_claims"] = len(cid)
            row[f"{agent_name}_agreed_with_peer_n"] = len(agreed)
            row[f"{agent_name}_disagreed_n"] = len(disagreed_refs)
            row[f"{agent_name}_state"] = pos.get("state")
        # Cross-leak indicator: does agent_b's round-1 reference any of
        # agent_a's round-1 claim_ids? Under a perfect barrier, round 1 should
        # have ZERO cross-references because neither agent saw the other.
        if r == 1 and "agent_a" in positions and "agent_b" in positions:
            a_ids = _claim_ids(positions["agent_a"])
            b_agreed = set(positions["agent_b"].get("agreed_with_peer") or [])
            b_disagreed = _disagreement_claim_id_refs(positions["agent_b"])
            row["round_1_b_referenced_a_claims"] = sorted(
                (b_agreed | b_disagreed) & a_ids
            )
            row["round_1_b_cross_leak_count"] = len(row["round_1_b_referenced_a_claims"])
        out["rounds"].append(row)

    # Verifier ledger analysis — use the parser-fix retro ledger if present
    # (canonical) else fall back to the live ledger.
    retro = run_dir / "retro_verifier_ledger_with_parser_fix.json"
    live = run_dir / "verifier_ledger.json"
    ledger_path = retro if retro.exists() else (live if live.exists() else None)
    if ledger_path:
        data = _load_if_exists(ledger_path)
        if isinstance(data, dict) and "entries" in data:
            entries = data["entries"]
        elif isinstance(data, list):
            entries = data
        else:
            entries = []
        out["ledger_path"] = str(ledger_path.relative_to(ROOT))
        out["ledger_total"] = len(entries)
        out["ledger_by_status"] = dict(Counter(e.get("status") for e in entries))
        out["ledger_by_lineage"] = dict(
            Counter(e.get("lineage_flag") for e in entries if e.get("lineage_flag"))
        )
        # Per-round breakdown
        out["ledger_per_round"] = {}
        for r in (1, 2, 3):
            rd = [e for e in entries if e.get("round") == r]
            if rd:
                out["ledger_per_round"][r] = {
                    "n": len(rd),
                    "by_status": dict(Counter(e.get("status") for e in rd)),
                    "lineage_flags": dict(
                        Counter(e.get("lineage_flag") for e in rd if e.get("lineage_flag"))
                    ),
                }

    return out


def main() -> None:
    results = {}
    for label, run_dir in RUNS.items():
        if not run_dir.exists():
            print(f"SKIP: {label} (run dir missing: {run_dir})")
            continue
        results[label] = analyze_run(label, run_dir)

    # Emit JSON for downstream consumers
    out_path = ROOT / "runs" / "plan-35-barrier-pilot" / "comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"wrote {out_path.relative_to(ROOT)}")
    print()

    # Human-readable summary
    print("=" * 78)
    print(f"{'RUN':<28} {'VERDICT':<26} {'ROUNDS':<8} {'LEDGER':<14}")
    print("-" * 78)
    for label, data in results.items():
        verdict = data.get("verdict", "-")
        rounds = data.get("total_rounds", "-")
        ledger_total = data.get("ledger_total", "-")
        print(f"{label:<28} {str(verdict):<26} {str(rounds):<8} {str(ledger_total):<14}")
    print()

    print("ROUND-1 CROSS-LEAK (agent_b round-1 referencing agent_a round-1 claim_ids):")
    print("-" * 78)
    for label, data in results.items():
        r1 = next((r for r in data.get("rounds", []) if r.get("round") == 1), {})
        leak = r1.get("round_1_b_cross_leak_count", "-")
        refs = r1.get("round_1_b_referenced_a_claims", [])
        print(f"  {label:<28} leak_count={leak} refs={refs}")
    print()

    print("LINEAGE FLAGS BY ROUND:")
    print("-" * 78)
    for label, data in results.items():
        prr = data.get("ledger_per_round", {})
        for r in sorted(prr.keys(), key=int):
            row = prr[r]
            print(f"  {label:<28} r{r}: {row.get('lineage_flags') or '{}'}")
    print()

    print("LEDGER STATUS BREAKDOWN:")
    print("-" * 78)
    for label, data in results.items():
        print(f"  {label:<28} {data.get('ledger_by_status')}")


if __name__ == "__main__":
    main()
