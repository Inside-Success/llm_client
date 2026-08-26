"""Adjudicating a judge's blocks.

The property under test is not agreement between runs. It is whether each block
identifies a real error, so a judge that blocks often on wording scores badly
even when it is perfectly self-consistent.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from llm_client.claim_adjudication import (
    UNWARRANTED_RULINGS,
    AdjudicatedBlock,
    AdjudicationResult,
    BlockUnderReview,
    BlockVerdict,
    blocks_from_claims,
)


def _block(claim_id: str = "c1") -> BlockUnderReview:
    return BlockUnderReview(
        claim_id=claim_id,
        claim_text="the leading rank can change under tested perturbations",
        severity="substantive_overstatement",
        objection="Every listed scenario still has h2 on top.",
    )


def _adj(ruling: str, claim_id: str = "c1") -> AdjudicatedBlock:
    return AdjudicatedBlock(
        block=_block(claim_id),
        verdict=BlockVerdict(ruling=ruling, reasoning="a reason of adequate length"),
    )


def test_an_upheld_objection_warrants_the_block():
    assert BlockVerdict(
        ruling="upheld", reasoning="the numbers do not show it"
    ).block_warranted


@pytest.mark.parametrize("ruling", ["stylistic", "overreaching", "unclear"])
def test_other_rulings_do_not_warrant_the_block(ruling):
    assert not BlockVerdict(ruling=ruling, reasoning="a reason of adequate length").block_warranted


def test_defensible_rate_ignores_undecidable_blocks():
    """An unclear ruling is a reporting gap, not a failure to be averaged in."""
    result = AdjudicationResult(
        adjudicated=[_adj("upheld", "a"), _adj("unclear", "b")]
    )
    assert result.defensible_rate == 1.0
    assert result.unclear and len(result.unclear) == 1


def test_defensible_rate_is_none_when_nothing_is_decidable():
    """None must not be reported as a zero score."""
    result = AdjudicationResult(adjudicated=[_adj("unclear", "a")])
    assert result.defensible_rate is None
    assert "n/a" in result.summary()


def test_a_self_consistent_judge_that_blocks_on_wording_scores_badly():
    """The regression this check exists to catch.

    Run-to-run agreement would score this judge perfectly; it blocked nine times
    on phrasing.
    """
    result = AdjudicationResult(
        adjudicated=[_adj("stylistic", f"c{i}") for i in range(9)]
        + [_adj("upheld", "c9")]
    )
    assert result.defensible_rate == 0.1
    assert len(result.stylistic_blocks) == 9


def test_unwarranted_covers_stylistic_and_overreaching_but_not_unclear():
    result = AdjudicationResult(
        adjudicated=[_adj("stylistic", "a"), _adj("overreaching", "b"), _adj("unclear", "c")]
    )
    assert {a.verdict.ruling for a in result.unwarranted} == UNWARRANTED_RULINGS
    assert len(result.unwarranted) == 2


def test_empty_result_reports_nothing_rather_than_a_perfect_score():
    result = AdjudicationResult(adjudicated=[])
    assert result.defensible_rate is None
    assert result.summary() == "no blocking claims to adjudicate"


def test_summary_accounts_for_every_block():
    result = AdjudicationResult(
        adjudicated=[
            _adj("upheld", "a"),
            _adj("stylistic", "b"),
            _adj("overreaching", "c"),
            _adj("unclear", "d"),
        ]
    )
    text = result.summary()
    assert "4 block(s)" in text
    assert "1 upheld" in text and "1 stylistic" in text
    assert "1 overreaching" in text and "1 unclear" in text


# ---------------------------------------------------------------------------
# Extraction from a judge's claims
# ---------------------------------------------------------------------------


class _Support(BaseModel):
    basis: str
    covers: str


class _Claim(BaseModel):
    claim_id: str
    claim_text: str
    severity: str
    reasoning: str
    supports: list[_Support] = []


def test_only_blocking_claims_are_extracted():
    claims = [
        _Claim(claim_id="ok", claim_text="fine", severity="grounded", reasoning="r"),
        _Claim(
            claim_id="bad",
            claim_text="not fine",
            severity="substantive_overstatement",
            reasoning="the evidence does not show it",
            supports=[_Support(basis="source_evidence", covers="all")],
        ),
    ]
    blocks = blocks_from_claims(
        claims, blocking_severities={"substantive_overstatement", "fabricated"}
    )
    assert [b.claim_id for b in blocks] == ["bad"]
    assert blocks[0].objection == "the evidence does not show it"
    assert blocks[0].supports == [{"basis": "source_evidence", "covers": "all"}]


def test_extraction_works_on_any_claim_shape_with_the_needed_fields():
    """Deliberately duck-typed so a project's own claim model works unchanged."""

    class Other(BaseModel):
        claim_id: str
        claim_text: str
        severity: str
        reasoning: str

    blocks = blocks_from_claims(
        [Other(claim_id="x", claim_text="t", severity="fabricated", reasoning="r")],
        blocking_severities={"fabricated"},
    )
    assert blocks[0].claim_id == "x" and blocks[0].supports == []


def test_a_verdict_needs_real_reasoning():
    with pytest.raises(ValidationError):
        BlockVerdict(ruling="upheld", reasoning="no")


def test_an_unknown_ruling_is_rejected():
    with pytest.raises(ValidationError):
        BlockVerdict(ruling="probably_fine", reasoning="a reason of adequate length")


# ---------------------------------------------------------------------------
# Multiple adjudicators
# ---------------------------------------------------------------------------


def _adj_by(ruling: str, claim_id: str, model: str) -> AdjudicatedBlock:
    return AdjudicatedBlock(
        block=_block(claim_id),
        verdict=BlockVerdict(ruling=ruling, reasoning="a reason of adequate length"),
        model=model,
    )


def test_disagreement_between_adjudicators_is_surfaced():
    """Measured on real data: two models split on one block because the prose
    was ambiguous, not because either was wrong."""
    result = AdjudicationResult(
        adjudicated=[
            _adj_by("overreaching", "c1", "luna"),
            _adj_by("upheld", "c1", "gemini"),
        ]
    )
    assert result.disputed == ["c1"]


def test_agreement_is_not_reported_as_a_dispute():
    result = AdjudicationResult(
        adjudicated=[
            _adj_by("overreaching", "c1", "luna"),
            _adj_by("stylistic", "c1", "gemini"),
        ]
    )
    assert result.disputed == []


def test_an_unclear_ruling_does_not_manufacture_a_dispute():
    result = AdjudicationResult(
        adjudicated=[_adj_by("upheld", "c1", "luna"), _adj_by("unclear", "c1", "gemini")]
    )
    assert result.disputed == []


def test_adjudication_requires_at_least_one_model():
    from llm_client.claim_adjudication import adjudicate_blocks

    with pytest.raises(ValueError, match="at least one adjudicating model"):
        adjudicate_blocks(
            [], context={}, task="t", trace_id="x", max_budget=1.0, model=[]
        )
