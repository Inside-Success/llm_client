"""Registration policy for claim-verification judges.

These pin the two properties that make the registry worth having: a model built
from the shared primitive passes without being listed by its generated name, and
anything else fails closed with a message that points at the primitive.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from llm_client.claim_verification import (
    ClaimVerificationReport,
    SeverityPolicy,
    build_report_model,
)
from llm_client.claim_verification_policy import (
    SANCTIONED_CLAIM_VERIFICATION_MODELS,
    assert_sanctioned_claim_verification,
    is_sanctioned_claim_verification,
    qualified_name,
)
from llm_client.core.errors import LLMConfigurationError


def _constrained():
    return build_report_model(
        artifact_refs={"bayesian"},
        bases={"source_evidence", "computed_artifact"},
        severities=SeverityPolicy.default().tier_names,
    )


def test_the_shared_report_is_registered():
    assert is_sanctioned_claim_verification(ClaimVerificationReport)


def test_build_report_model_output_is_sanctioned():
    assert is_sanctioned_claim_verification(_constrained())


def test_a_per_call_generated_subclass_passes_without_being_listed():
    """Per-call models cannot be enumerated in a shared allowlist.

    process_tracing binds its evidence-ID enum per target, producing names like
    `CentralClaimEntailmentReviewForMechanismBoundEvidenceIds` that differ by
    call site. Registration therefore resolves through ancestry; otherwise every
    caller would have to add its own generated name here, which is exactly the
    per-project configuration this module exists to prevent.
    """
    from pydantic import create_model

    model = create_model(
        "ClaimVerificationReportBoundEvidenceIds",
        __base__=ClaimVerificationReport,
    )
    assert qualified_name(model) not in SANCTIONED_CLAIM_VERIFICATION_MODELS
    assert is_sanctioned_claim_verification(model)


def test_a_bespoke_judge_fails_closed():
    class OneOffJudge(BaseModel):
        verdicts: list[str]

    with pytest.raises(LLMConfigurationError, match="unregistered claim-verification"):
        assert_sanctioned_claim_verification(OneOffJudge, task="someproject.review")


def test_the_error_points_at_the_primitive_not_just_the_allowlist():
    """The intended fix is to use the shared primitive, not to widen the list."""

    class OneOffJudge(BaseModel):
        verdicts: list[str]

    with pytest.raises(LLMConfigurationError) as excinfo:
        assert_sanctioned_claim_verification(OneOffJudge, task="someproject.review")
    message = str(excinfo.value)
    assert "llm_client.claim_verification" in message
    assert "someproject.review" in message


def test_subclassing_a_sanctioned_model_stays_sanctioned():
    """A subclass still implements the sanctioned contract, so it is allowed.

    The registry is not trying to stop specialisation; it is trying to stop a
    parallel judge with its own severity vocabulary.
    """

    class NarrowedReport(ClaimVerificationReport):
        pass

    assert is_sanctioned_claim_verification(NarrowedReport)


def test_registry_entries_are_fully_qualified():
    for entry in SANCTIONED_CLAIM_VERIFICATION_MODELS:
        assert "." in entry, entry
        assert not entry.endswith("."), entry


def test_process_tracing_reviewer_is_registered():
    """pt's terminal reviewer migrated onto the shared rubric, so it is allowed.

    Listed by name because llm_client cannot import process_tracing; the tier
    vocabulary itself is pinned on the pt side against the rubric shipped by the
    llm_client revision that repo pins.
    """
    assert any(
        entry.startswith("pt.schemas.CentralClaimEntailmentReview")
        for entry in SANCTIONED_CLAIM_VERIFICATION_MODELS
    )


def test_qualified_name_is_module_scoped():
    assert qualified_name(ClaimVerificationReport) == (
        "llm_client.claim_verification.ClaimVerificationReport"
    )
