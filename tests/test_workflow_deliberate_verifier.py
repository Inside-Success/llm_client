"""Unit tests for the Plan #34 deliberation verifier / adjudicator.

Tests are pure-Python (no LangGraph, no LLM) — the verifier itself has no
LLM dependency, so these run anywhere pytest does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_client.workflow.deliberate_verifier import (
    LedgerEntry,
    VerifierLedger,
    parse_evidence_path,
    verify_position,
    verify_round,
)


# ---------------------------------------------------------------------------
# parse_evidence_path
# ---------------------------------------------------------------------------


def test_parse_evidence_path_file_line_range() -> None:
    cites = parse_evidence_path("foo/bar.py:10-20")
    assert len(cites) == 1
    assert cites[0].parseable
    assert cites[0].file_path == "foo/bar.py"
    assert cites[0].line_range == (10, 20)


def test_parse_evidence_path_single_line() -> None:
    cites = parse_evidence_path("foo.py:42")
    assert cites[0].line_range == (42, 42)


def test_parse_evidence_path_section() -> None:
    cites = parse_evidence_path("docs/plan.md#step-4")
    assert cites[0].parseable
    assert cites[0].file_path == "docs/plan.md"
    assert cites[0].section == "step-4"


def test_parse_evidence_path_multi_citation() -> None:
    cites = parse_evidence_path("a.py:1-10; b.md#sec; c.py:42")
    assert len(cites) == 3
    assert [c.parseable for c in cites] == [True, True, True]
    assert cites[1].section == "sec"


def test_parse_evidence_path_unparseable() -> None:
    cites = parse_evidence_path("because I said so")
    assert not cites[0].parseable
    assert cites[0].file_path is None


def test_parse_evidence_path_empty() -> None:
    cites = parse_evidence_path("")
    assert len(cites) == 1
    assert not cites[0].parseable


def test_parse_evidence_path_comma_range_list() -> None:
    # Real-world pattern from the v2 self-deliberation: agents emit multiple
    # line ranges in one citation, comma-separated after the colon.
    cites = parse_evidence_path("deliberate.py:4-7,9-17,364-380,466-480")
    assert len(cites) == 4
    assert [c.parseable for c in cites] == [True, True, True, True]
    assert all(c.file_path == "deliberate.py" for c in cites)
    assert [c.line_range for c in cites] == [(4, 7), (9, 17), (364, 380), (466, 480)]


def test_parse_evidence_path_comma_range_single_line() -> None:
    cites = parse_evidence_path("foo.py:1-5,42")
    assert len(cites) == 2
    assert cites[1].line_range == (42, 42)


def test_parse_evidence_path_mixed_semicolon_and_comma() -> None:
    cites = parse_evidence_path("a.py:1-5,10-15; b.md#sec; c.py:42")
    assert len(cites) == 4
    assert [c.file_path for c in cites] == ["a.py", "a.py", "b.md", "c.py"]
    assert cites[2].section == "sec"


# ---------------------------------------------------------------------------
# verify_position (per-citation resolution)
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_file(tmp_path: Path) -> Path:
    """Workspace with a 30-line file we can cite into."""
    f = tmp_path / "foo.py"
    f.write_text("\n".join(f"line {i}" for i in range(1, 31)) + "\n")
    return tmp_path


def _make_position(
    *,
    agent_name: str = "agent_a",
    round_num: int = 1,
    claims: list[dict] | None = None,
    disagreed: list[dict] | None = None,
    agreed: list[str] | None = None,
) -> dict:
    return {
        "agent_name": agent_name,
        "round": round_num,
        "claims": claims or [],
        "evidence": [],
        "open_questions": [],
        "agreed_with_peer": agreed or [],
        "disagreed_with_peer": disagreed or [],
        "confidence": "medium",
        "state": "initial",
        "reviewer_summary": "",
        "reviewer_model": "",
    }


def _claim(claim_id: str, evidence: str, text: str = "a claim") -> dict:
    return {
        "claim_id": claim_id,
        "claim": text,
        "severity": "warn",
        "evidence_path": evidence,
    }


def test_verify_position_resolved_file_line(workspace_with_file: Path) -> None:
    pos = _make_position(claims=[_claim("c1", "foo.py:10-15")])
    entries = verify_position(pos, str(workspace_with_file))
    assert len(entries) == 1
    e = entries[0]
    assert e.status == "verified"
    assert e.line_range == (10, 15)
    assert e.snippet is not None
    assert "line 10" in e.snippet
    assert "line 15" in e.snippet


def test_verify_position_file_not_found(workspace_with_file: Path) -> None:
    pos = _make_position(claims=[_claim("c1", "nonexistent.py:1")])
    entries = verify_position(pos, str(workspace_with_file))
    assert entries[0].status == "file_not_found"
    assert entries[0].snippet is None


def test_verify_position_unparseable_evidence(workspace_with_file: Path) -> None:
    pos = _make_position(claims=[_claim("c1", "because I said so")])
    entries = verify_position(pos, str(workspace_with_file))
    assert entries[0].status == "unparseable_evidence"


def test_verify_position_line_out_of_range(workspace_with_file: Path) -> None:
    pos = _make_position(claims=[_claim("c1", "foo.py:100-200")])
    entries = verify_position(pos, str(workspace_with_file))
    assert entries[0].status == "unresolved_path"
    assert "out_of_bounds" in entries[0].notes


def test_verify_position_multi_citation_yields_multiple_entries(workspace_with_file: Path) -> None:
    pos = _make_position(claims=[_claim("c1", "foo.py:1-5; foo.py:20-25")])
    entries = verify_position(pos, str(workspace_with_file))
    assert len(entries) == 2
    assert all(e.status == "verified" for e in entries)


def test_verify_position_walks_disagreements(workspace_with_file: Path) -> None:
    pos = _make_position(
        disagreed=[{
            "peer_claim_id": "b1",
            "my_counterclaim": "no",
            "evidence_path": "foo.py:5",
        }]
    )
    entries = verify_position(pos, str(workspace_with_file))
    assert len(entries) == 1
    assert entries[0].status == "verified"
    assert entries[0].claim_id == "disagreement_against_b1"


# ---------------------------------------------------------------------------
# Lineage tracking
# ---------------------------------------------------------------------------


def test_lineage_detects_silent_rename(workspace_with_file: Path) -> None:
    """Same claim text, different claim_id between rounds → silent_rename."""
    prior = _make_position(
        round_num=1,
        claims=[_claim("a1", "foo.py:1", text="the prompt is contradictory")],
    )
    current = _make_position(
        round_num=2,
        claims=[_claim("a1_revised", "foo.py:1", text="the prompt is contradictory")],
    )
    new_ledger = verify_round(
        latest_positions={"agent_a": current, "agent_b": _make_position(agent_name="agent_b", round_num=2)},
        prior_positions_by_agent={"agent_a": prior, "agent_b": _make_position(agent_name="agent_b", round_num=1)},
        prior_ledger=VerifierLedger(),
        round_num=2,
        workspace_path=str(workspace_with_file),
    )
    rename_entries = [e for e in new_ledger.entries if e.lineage_flag == "silent_rename"]
    assert len(rename_entries) == 1
    assert rename_entries[0].claim_id == "a1_revised"
    assert "a1" in rename_entries[0].lineage_detail


def test_lineage_detects_silent_retire(workspace_with_file: Path) -> None:
    """claim_id in prior, absent in current with no rename match → silent_retire."""
    prior = _make_position(
        round_num=1,
        claims=[_claim("a3", "foo.py:1", text="a claim that gets dropped")],
    )
    current = _make_position(
        round_num=2,
        claims=[_claim("a4", "foo.py:2", text="a completely different claim")],
    )
    new_ledger = verify_round(
        latest_positions={"agent_a": current, "agent_b": _make_position(agent_name="agent_b", round_num=2)},
        prior_positions_by_agent={"agent_a": prior, "agent_b": _make_position(agent_name="agent_b", round_num=1)},
        prior_ledger=VerifierLedger(),
        round_num=2,
        workspace_path=str(workspace_with_file),
    )
    retire_entries = [e for e in new_ledger.entries if e.lineage_flag == "silent_retire"]
    assert len(retire_entries) == 1
    assert retire_entries[0].claim_id == "a3"


def test_lineage_detects_fabricated_peer_ref(workspace_with_file: Path) -> None:
    """agreed_with_peer references a claim_id that doesn't exist in the peer's position."""
    agent_a = _make_position(
        round_num=2,
        claims=[_claim("a1", "foo.py:1")],
        agreed=["b99"],  # fabricated
    )
    agent_b = _make_position(
        agent_name="agent_b",
        round_num=2,
        claims=[_claim("b1", "foo.py:2")],
    )
    new_ledger = verify_round(
        latest_positions={"agent_a": agent_a, "agent_b": agent_b},
        prior_positions_by_agent={},
        prior_ledger=VerifierLedger(),
        round_num=2,
        workspace_path=str(workspace_with_file),
    )
    fab_entries = [e for e in new_ledger.entries if e.lineage_flag == "fabricated_peer_ref"]
    assert len(fab_entries) == 1
    assert fab_entries[0].claim_id == "b99"


def test_lineage_does_not_falsely_flag_rename_aware_peer_refs(workspace_with_file: Path) -> None:
    """REGRESSION (Plan #35 background review): under the barrier, an agent
    legitimately references the peer's round-(N-1) claim_ids (which it actually
    saw). If the peer renames those claim_ids in round N, the verifier MUST
    compare against the peer's PRIOR snapshot, not the peer's current. The
    pre-fix code compared against latest_positions[peer] and produced false
    fabricated_peer_ref flags. This test pins that semantics by:

    1. Setting up peer's prior with claim_id 'b1' (what agent_a saw)
    2. Setting peer's current with claim_id 'b1_renamed' (silent rename)
    3. Agent_a r2 agrees with 'b1' (correctly — that's what it saw)
    4. Asserting NO fabricated_peer_ref fires for 'b1'.

    A revert of the Plan #35 verifier fix (comparing against latest_positions
    instead of prior_positions_by_agent) would flag 'b1' as fabricated because
    peer's current shows only 'b1_renamed'. This test would fail loud."""
    peer_prior = _make_position(
        agent_name="agent_b",
        round_num=1,
        claims=[_claim("b1", "foo.py:1", text="original claim text")],
    )
    peer_current = _make_position(
        agent_name="agent_b",
        round_num=2,
        claims=[_claim("b1_renamed", "foo.py:1", text="original claim text")],
    )
    agent_a_current = _make_position(
        round_num=2,
        claims=[_claim("a1", "foo.py:1")],
        agreed=["b1"],  # references what agent_a actually saw under barrier
    )
    new_ledger = verify_round(
        latest_positions={"agent_a": agent_a_current, "agent_b": peer_current},
        prior_positions_by_agent={
            "agent_a": _make_position(round_num=1, claims=[_claim("a1", "foo.py:1")]),
            "agent_b": peer_prior,
        },
        prior_ledger=VerifierLedger(),
        round_num=2,
        workspace_path=str(workspace_with_file),
    )
    fabricated_b1 = [
        e for e in new_ledger.entries
        if e.lineage_flag == "fabricated_peer_ref" and e.claim_id == "b1"
    ]
    assert fabricated_b1 == [], (
        f"REGRESSION: 'b1' is a legitimate reference to peer's round-1 snapshot, "
        f"but was flagged as fabricated_peer_ref. The verifier is comparing "
        f"against peer's CURRENT position (where b1 was renamed to b1_renamed) "
        f"instead of peer's PRIOR snapshot. Got entries: {fabricated_b1}"
    )


def test_lineage_detects_fabricated_disagreement_target(workspace_with_file: Path) -> None:
    """disagreed_with_peer.peer_claim_id that doesn't match peer's claim ids."""
    agent_a = _make_position(
        round_num=2,
        claims=[_claim("a1", "foo.py:1")],
        disagreed=[{
            "peer_claim_id": "b_nonexistent",
            "my_counterclaim": "nope",
            "evidence_path": "foo.py:1",
        }],
    )
    agent_b = _make_position(
        agent_name="agent_b",
        round_num=2,
        claims=[_claim("b1", "foo.py:2")],
    )
    new_ledger = verify_round(
        latest_positions={"agent_a": agent_a, "agent_b": agent_b},
        prior_positions_by_agent={},
        prior_ledger=VerifierLedger(),
        round_num=2,
        workspace_path=str(workspace_with_file),
    )
    fab_entries = [
        e for e in new_ledger.entries
        if e.lineage_flag == "fabricated_peer_ref" and e.claim_id == "b_nonexistent"
    ]
    assert len(fab_entries) == 1


# ---------------------------------------------------------------------------
# VerifierLedger helpers
# ---------------------------------------------------------------------------


def test_ledger_latest_round_empty() -> None:
    assert VerifierLedger().latest_round() is None


def test_ledger_has_unverified_in_round() -> None:
    ledger = VerifierLedger()
    ledger.extend([
        LedgerEntry(agent_name="a", round=1, claim_id="c1", evidence_path="x", status="verified"),
        LedgerEntry(agent_name="a", round=1, claim_id="c2", evidence_path="y", status="file_not_found"),
        LedgerEntry(agent_name="a", round=2, claim_id="c3", evidence_path="z", status="verified"),
    ])
    assert ledger.has_unverified_in_round(1)
    assert not ledger.has_unverified_in_round(2)
    assert ledger.latest_round() == 2


def test_ledger_has_lineage_flag_in_round() -> None:
    ledger = VerifierLedger()
    ledger.extend([
        LedgerEntry(
            agent_name="a",
            round=2,
            claim_id="c1",
            evidence_path="",
            status="content_mismatch_warning",
            lineage_flag="silent_rename",
        ),
    ])
    assert ledger.has_lineage_flag_in_round(2)
    assert not ledger.has_lineage_flag_in_round(1)
