"""Tests for graduated-severity claim verification.

The behavioural claims under test are the ones that distinguish this primitive
from the binary judge it replaces: a middle outcome exists, gating is
worst-tier-wins rather than an average, a claim can carry support of more than
one kind, and the judge's citations are checked rather than trusted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_client.claim_verification import (
    ArtifactLocator,
    ClaimSupport,
    ClaimVerificationReport,
    SeverityPolicy,
    VerifiedClaim,
    build_claim_verification_messages,
    load_severity_rubric,
    pointer_repair_hints,
    resolve_json_pointer,
    verify_report,
)

BAYESIAN = {
    "hypotheses": [
        {"id": "h1", "prior": 0.25, "posterior": 0.18},
        {"id": "h2", "prior": 0.25, "posterior": 0.41},
    ]
}
EVIDENCE_IDS = {"evi_planning", "evi_design", "evi_coercion"}


def _claim(claim_id: str, severity: str, supports=None) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim_id,
        claim_text="some atomic claim text",
        severity=severity,
        supports=supports
        if supports is not None
        else [
            ClaimSupport(
                basis="source_evidence",
                covers="the whole claim",
                evidence_ids=["evi_planning"],
            )
        ],
        reasoning="reasoning that is long enough",
    )


def _report(*claims: VerifiedClaim) -> ClaimVerificationReport:
    return ClaimVerificationReport(
        claims=list(claims),
        overall_assessment="An assessment sentence of sufficient length.",
    )


# ---------------------------------------------------------------------------
# Rubric and policy
# ---------------------------------------------------------------------------


def test_shared_rubric_defines_the_graduated_tiers():
    policy = SeverityPolicy.default()
    assert policy.tier_names == [
        "grounded",
        "stylistic_gloss",
        "unattributed_computed_claim",
        "composite_claim",
        "substantive_overstatement",
        "fabricated",
    ]


def test_rubric_is_an_ordinary_categorical_rubric():
    """Tiers reuse the shared rubric shape, so they stay reviewable and versioned."""
    rubric = load_severity_rubric()
    dim = rubric.get_dimension("claim_severity")
    assert dim is not None
    assert dim.scale == "categorical"
    assert all(c.description.strip() for c in dim.categories)


@pytest.mark.parametrize(
    "severity,expected",
    [
        ("grounded", "accepted"),
        ("stylistic_gloss", "accepted"),
        ("unattributed_computed_claim", "repairable"),
        ("composite_claim", "repairable"),
        ("substantive_overstatement", "blocked"),
        ("fabricated", "blocked"),
    ],
)
def test_tier_outcomes(severity, expected):
    assert SeverityPolicy.default().outcome(severity) == expected


def test_stylistic_gloss_does_not_block():
    """The regression this primitive exists to prevent.

    Under the binary judge, 'substantial' missing from the source blocked the
    whole review. It must now be an accepted outcome.
    """
    policy = SeverityPolicy.default()
    result = verify_report(
        _report(_claim("c1", "grounded"), _claim("c2", "stylistic_gloss")),
        evidence_ids=EVIDENCE_IDS,
        artifacts={},
        policy=policy,
    )
    assert result.status == "accepted"
    assert result.blocking_claims == []


def test_unattributed_computed_claim_is_repairable_not_blocking():
    policy = SeverityPolicy.default()
    result = verify_report(
        _report(_claim("c1", "grounded"), _claim("c2", "unattributed_computed_claim")),
        evidence_ids=EVIDENCE_IDS,
        artifacts={},
        policy=policy,
    )
    assert result.status == "repairable"
    assert result.repairable_claims == ["c2"]
    assert result.blocking_claims == []


def test_gate_is_worst_tier_wins_not_an_average():
    """One fabrication blocks even when every other claim is grounded.

    A weighted mean over the same claims scores ~0.98 — high enough to look
    acceptable — which is why acceptance must not be an average.
    """
    policy = SeverityPolicy.default()
    claims = [_claim(f"c{i}", "grounded") for i in range(50)]
    claims.append(_claim("bad", "fabricated"))
    result = verify_report(
        _report(*claims), evidence_ids=EVIDENCE_IDS, artifacts={}, policy=policy
    )
    assert result.status == "blocked"
    assert result.blocking_claims == ["bad"]

    mean = sum(policy.tier_score(c.severity) for c in claims) / len(claims)
    assert mean > 0.95, "the averaging trap this gate must not fall into"


def test_unknown_tier_fails_loud():
    with pytest.raises(ValueError, match="Unknown severity tier"):
        SeverityPolicy.default().outcome("probably_fine")


def test_status_over_zero_claims_is_an_error_not_an_acceptance():
    with pytest.raises(ValueError, match="zero claims"):
        SeverityPolicy.default().status([])


def test_repair_threshold_cannot_exceed_accept_threshold():
    with pytest.raises(ValidationError):
        SeverityPolicy(
            rubric=load_severity_rubric(),
            accept_at_or_above=0.4,
            repair_at_or_above=0.8,
        )


# ---------------------------------------------------------------------------
# Multi-support provenance — the fix for the verdict-flip root cause
# ---------------------------------------------------------------------------


def test_claim_may_carry_support_of_two_different_kinds():
    """A claim fusing an observation and a computed result needs both records.

    Forcing one support regime onto such a claim is what made byte-identical
    prose flip between entailed and overstated across runs.
    """
    claim = _claim(
        "verdict_h1_c1",
        "grounded",
        supports=[
            ClaimSupport(
                basis="source_evidence",
                covers="has favorable planning and institutional-design traces",
                evidence_ids=["evi_planning", "evi_design"],
            ),
            ClaimSupport(
                basis="computed_artifact",
                covers="comparative support is below its prior",
                artifact_locators=[
                    ArtifactLocator(
                        artifact_ref="bayesian",
                        json_pointer="/hypotheses/0/posterior",
                    )
                ],
            ),
        ],
    )
    result = verify_report(
        _report(claim),
        evidence_ids=EVIDENCE_IDS,
        artifacts={"bayesian": BAYESIAN},
        policy=SeverityPolicy.default(),
    )
    assert result.status == "accepted"
    assert result.citation_errors == []
    assert {s.basis for s in claim.supports} == {"source_evidence", "computed_artifact"}


def test_support_must_cite_something():
    with pytest.raises(ValidationError):
        ClaimSupport(basis="source_evidence", covers="everything")


def test_support_rejects_duplicate_citations():
    with pytest.raises(ValidationError):
        ClaimSupport(
            basis="source_evidence",
            covers="x",
            evidence_ids=["evi_planning", "evi_planning"],
        )


def test_report_rejects_duplicate_claim_ids():
    with pytest.raises(ValidationError):
        _report(_claim("c1", "grounded"), _claim("c1", "grounded"))


# ---------------------------------------------------------------------------
# Deterministic citation verification
# ---------------------------------------------------------------------------


def test_invented_evidence_id_is_caught_not_trusted():
    claim = _claim(
        "c1",
        "grounded",
        supports=[
            ClaimSupport(
                basis="source_evidence",
                covers="all",
                evidence_ids=["evi_that_sounds_plausible"],
            )
        ],
    )
    result = verify_report(
        _report(claim),
        evidence_ids=EVIDENCE_IDS,
        artifacts={},
        policy=SeverityPolicy.default(),
    )
    assert result.status == "blocked"
    assert [e.kind for e in result.citation_errors] == ["unknown_evidence_id"]


def test_unresolved_pointer_reports_repair_hints():
    claim = _claim(
        "c1",
        "grounded",
        supports=[
            ClaimSupport(
                basis="computed_artifact",
                covers="all",
                artifact_locators=[
                    ArtifactLocator(artifact_ref="bayesian", json_pointer="/posterior")
                ],
            )
        ],
    )
    result = verify_report(
        _report(claim),
        evidence_ids=EVIDENCE_IDS,
        artifacts={"bayesian": BAYESIAN},
        policy=SeverityPolicy.default(),
    )
    assert result.status == "blocked"
    (error,) = result.citation_errors
    assert error.kind == "unresolved_pointer"
    assert "/hypotheses/0/posterior" in error.repair_hints


def test_unknown_artifact_lists_available_ones():
    claim = _claim(
        "c1",
        "grounded",
        supports=[
            ClaimSupport(
                basis="computed_artifact",
                covers="all",
                artifact_locators=[
                    ArtifactLocator(artifact_ref="testing", json_pointer="")
                ],
            )
        ],
    )
    result = verify_report(
        _report(claim),
        evidence_ids=EVIDENCE_IDS,
        artifacts={"bayesian": BAYESIAN},
        policy=SeverityPolicy.default(),
    )
    (error,) = result.citation_errors
    assert error.kind == "unknown_artifact"
    assert error.repair_hints == ["bayesian"]


def test_citation_errors_can_be_non_blocking_when_caller_opts_out():
    claim = _claim(
        "c1",
        "grounded",
        supports=[
            ClaimSupport(basis="source_evidence", covers="all", evidence_ids=["nope"])
        ],
    )
    result = verify_report(
        _report(claim),
        evidence_ids=EVIDENCE_IDS,
        artifacts={},
        policy=SeverityPolicy.default(),
        citation_errors_block=False,
    )
    assert result.status == "accepted"
    assert len(result.citation_errors) == 1


# ---------------------------------------------------------------------------
# RFC 6901 pointer handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pointer,expected",
    [
        ("", BAYESIAN),
        ("/hypotheses/1/id", "h2"),
        ("/hypotheses/0/posterior", 0.18),
    ],
)
def test_pointer_resolution(pointer, expected):
    assert resolve_json_pointer(BAYESIAN, pointer) == expected


def test_pointer_unescapes_rfc6901_tokens():
    doc = {"a/b": {"c~d": 7}}
    assert resolve_json_pointer(doc, "/a~1b/c~0d") == 7


@pytest.mark.parametrize(
    "pointer", ["/hypotheses/9/id", "/missing", "/hypotheses/notanindex"]
)
def test_bad_pointer_fails_loud(pointer):
    with pytest.raises(ValueError, match="does not resolve"):
        resolve_json_pointer(BAYESIAN, pointer)


def test_repair_hints_are_bounded():
    doc = {"rows": [{"score": i} for i in range(100)]}
    assert len(pointer_repair_hints(doc, "/score", limit=20)) == 20


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_carries_tiers_and_bases_to_the_judge():
    messages = build_claim_verification_messages(
        [{"claim_id": "c1", "claim_text": "a claim"}],
        evidence=[{"id": "evi_planning", "text": "..."}],
        artifacts={"bayesian": BAYESIAN},
        policy=SeverityPolicy.default(),
    )
    content = "\n".join(m["content"] for m in messages)
    for tier in SeverityPolicy.default().tier_names:
        assert tier in content
    assert "source_evidence" in content
    assert "computed_artifact" in content
    assert "least severe tier" in content


# ---------------------------------------------------------------------------
# Closed vocabularies at the schema level
# ---------------------------------------------------------------------------


def _constrained():
    from llm_client.claim_verification import build_report_model

    return build_report_model(
        artifact_refs={"bayesian", "diagnostic_matrix"},
        bases={"source_evidence", "computed_artifact"},
        severities=SeverityPolicy.default().tier_names,
    )


def _payload(**overrides):
    claim = {
        "claim_id": "c1",
        "claim_text": "a claim",
        "severity": "grounded",
        "reasoning": "reasoning long enough",
        "supports": [
            {
                "basis": "computed_artifact",
                "covers": "all of it",
                "artifact_locators": [
                    {"artifact_ref": "bayesian", "json_pointer": "/hypotheses/0/posterior"}
                ],
            }
        ],
    }
    claim.update(overrides)
    return {
        "claims": [claim],
        "overall_assessment": "An assessment sentence of sufficient length.",
    }


def test_constrained_model_accepts_exact_identifiers():
    report = _constrained().model_validate(_payload())
    assert report.claims[0].supports[0].artifact_locators[0].artifact_ref == "bayesian"


def test_prose_description_cannot_be_used_as_an_artifact_ref():
    """The failure observed on a real run: a description where a name belongs."""
    bad = _payload()
    bad["claims"][0]["supports"][0]["artifact_locators"][0]["artifact_ref"] = (
        "Bayes posterior and diagnostic matrix entries for hypothesis h1"
    )
    with pytest.raises(ValidationError):
        _constrained().model_validate(bad)


def test_unknown_basis_is_rejected_at_the_schema():
    with pytest.raises(ValidationError):
        _constrained().model_validate(
            _payload(supports=[{"basis": "vibes", "covers": "x", "evidence_ids": ["e"]}])
        )


def test_unknown_severity_is_rejected_at_the_schema():
    with pytest.raises(ValidationError):
        _constrained().model_validate(_payload(severity="probably_fine"))


def test_no_artifacts_supplied_means_no_locators_are_representable():
    from llm_client.claim_verification import build_report_model

    model = build_report_model(
        artifact_refs=set(),
        bases={"source_evidence"},
        severities=SeverityPolicy.default().tier_names,
    )
    with pytest.raises(ValidationError):
        model.model_validate(
            _payload(
                supports=[
                    {
                        "basis": "source_evidence",
                        "covers": "x",
                        "artifact_locators": [
                            {"artifact_ref": "bayesian", "json_pointer": "/a"}
                        ],
                    }
                ]
            )
        )


def test_build_report_model_requires_vocabularies():
    from llm_client.claim_verification import build_report_model

    with pytest.raises(ValueError, match="support basis"):
        build_report_model(artifact_refs=set(), bases=set(), severities=["grounded"])
    with pytest.raises(ValueError, match="severity tier"):
        build_report_model(artifact_refs=set(), bases={"source_evidence"}, severities=[])
