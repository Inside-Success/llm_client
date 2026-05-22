"""Tests for the duet TaskFamily registry and built-in profiles."""

from __future__ import annotations

import pytest

from llm_client.workflow.duet import ImplementReview, PlanReview
from llm_client.workflow.duet_base import (
    ImplementReviewBase,
    PlanReviewBase,
    TaskFamily,
)
from llm_client.workflow.duet_registry import (
    _reset_for_tests,
    get_task_family,
    list_task_families,
    register_task_family,
)


@pytest.fixture
def empty_registry():
    """Yield with the registry cleared, then restore built-ins after the test.

    Restoration re-registers the existing profile objects rather than reloading
    the modules — reloading creates fresh class objects, which would break any
    other test that imported the schema classes at module-import time.
    """
    from llm_client.workflow.profiles.generic import GENERIC_PROFILE
    from llm_client.workflow.profiles.plan_doc_review import PLAN_DOC_REVIEW_PROFILE
    from llm_client.workflow.profiles.twin_update import TWIN_UPDATE_PROFILE

    _reset_for_tests()
    yield
    _reset_for_tests()
    register_task_family(GENERIC_PROFILE)
    register_task_family(PLAN_DOC_REVIEW_PROFILE)
    register_task_family(TWIN_UPDATE_PROFILE)


class _MinimalPlanReview(PlanReviewBase):
    pass


class _MinimalImplementReview(ImplementReviewBase):
    pass


def _minimal_family(name: str) -> TaskFamily:
    return TaskFamily(
        name=name,
        plan_review_schema=_MinimalPlanReview,
        implement_review_schema=_MinimalImplementReview,
    )


def test_registry_register_and_get(empty_registry) -> None:
    family = _minimal_family("test_family")
    register_task_family(family)
    assert get_task_family("test_family") is family


def test_registry_get_missing_raises(empty_registry) -> None:
    with pytest.raises(KeyError, match="not registered"):
        get_task_family("nonexistent_family")


def test_registry_double_register_raises(empty_registry) -> None:
    register_task_family(_minimal_family("dup"))
    with pytest.raises(ValueError, match="already registered"):
        register_task_family(_minimal_family("dup"))


def test_registry_list_returns_sorted_names(empty_registry) -> None:
    register_task_family(_minimal_family("z_family"))
    register_task_family(_minimal_family("a_family"))
    assert list_task_families() == ["a_family", "z_family"]


def test_generic_profile_is_registered_at_workflow_import() -> None:
    """``from llm_client.workflow import build_duet_workflow`` should also
    register the built-in profiles via the side-effect import in
    ``llm_client.workflow.__init__``.

    Verified by importing the package (which triggers the side-effect import
    of ``profiles``) and checking the registry. We do NOT reload — that would
    create fresh class objects and break ``is`` comparisons in other tests.
    """
    import llm_client.workflow  # noqa: F401

    families = list_task_families()
    assert "generic" in families
    assert "plan_doc_review" in families


def test_generic_profile_carries_today_schemas() -> None:
    """The ``generic`` profile must keep using PlanReview/ImplementReview
    so existing duet callers see no behavior change.
    """
    family = get_task_family("generic")
    assert family.plan_review_schema is PlanReview
    assert family.implement_review_schema is ImplementReview


def test_plan_doc_review_schema_has_template_section_fields() -> None:
    """``plan_doc_review`` profile must surface the new plan-doc fields."""
    from llm_client.workflow.profiles.plan_doc_review import PlanDocPlanReview

    family = get_task_family("plan_doc_review")
    assert family.plan_review_schema is PlanDocPlanReview

    # Schema accepts a minimal verdict-only payload (subclass of PlanReview).
    review = PlanDocPlanReview(verdict="pass")
    assert review.template_section_misses == []
    assert review.references_unverified == []
    assert review.acceptance_criteria_unmeasurable == []

    # Schema fields list a fully populated payload.
    review = PlanDocPlanReview(
        verdict="revise",
        template_section_misses=["Required Tests"],
        references_unverified=[{"cited_as": "foo.py:1-10", "reason_unverified": "no file"}],
        acceptance_criteria_unmeasurable=["all tests pass"],
    )
    assert review.template_section_misses == ["Required Tests"]
    assert review.references_unverified[0].cited_as == "foo.py:1-10"


def test_plan_doc_review_uses_generic_implement_schema() -> None:
    """The plan-doc-review profile reuses the generic impl review (no specialization needed)."""
    family = get_task_family("plan_doc_review")
    assert family.implement_review_schema is ImplementReview


def test_plan_doc_review_addendum_mentions_template_md() -> None:
    """Reviewer must be told about the TEMPLATE.md sections it should check."""
    family = get_task_family("plan_doc_review")
    assert "TEMPLATE.md" in family.plan_review_prompt_addendum
    assert "template_section_misses" in family.plan_review_prompt_addendum
    assert "references_unverified" in family.plan_review_prompt_addendum


def test_planreview_is_subclass_of_base() -> None:
    """Generic PlanReview must inherit from PlanReviewBase so subclassing
    profiles can extend it. Same for ImplementReview.
    """
    assert issubclass(PlanReview, PlanReviewBase)
    assert issubclass(ImplementReview, ImplementReviewBase)


# ---------------------------------------------------------------------------
# twin_update profile
# ---------------------------------------------------------------------------


def test_twin_update_profile_is_registered_at_import() -> None:
    """Importing ``llm_client.workflow.profiles`` must register ``twin_update``."""
    import llm_client.workflow.profiles  # noqa: F401

    assert "twin_update" in list_task_families()


def test_twin_update_plan_review_has_pcm_and_rubric_fields() -> None:
    """The plan-review schema must surface all four specialized lists."""
    from llm_client.workflow.profiles.twin_update import (
        PcmLayerFinding,
        ProofAuthorityGap,
        ScopeViolation,
        TwinFidelityRubricMiss,
        TwinUpdatePlanReview,
    )

    review = TwinUpdatePlanReview(
        verdict="revise",
        pcm_layer_findings=[
            PcmLayerFinding(
                layer="Voice",
                finding="signature phrase removed",
                severity="high",
                evidence_path="prompts/foo.md:42",
            )
        ],
        twin_fidelity_rubric_misses=[
            TwinFidelityRubricMiss(
                axis="axis_b_proof_depth",
                item="qa_ready",
                why_missed="no surface authority matrix",
                suggested_remediation="generate matrix and rerun",
            )
        ],
        proof_authority_gaps=[
            ProofAuthorityGap(
                claim="bug is fixed in prod",
                missing_artifact="published-prod replay",
                why_blocking="claim is current-behavior",
                narrower_claim_still_safe="dev surface improved",
            )
        ],
        scope_violations=[
            ScopeViolation(
                proposed_change="add medical advice template",
                customer_constraint_violated="no medical advice",
                evidence_path="customer_files/foo/constraints.yaml",
            )
        ],
    )
    assert review.pcm_layer_findings[0].layer == "Voice"
    assert review.twin_fidelity_rubric_misses[0].axis == "axis_b_proof_depth"
    assert review.proof_authority_gaps[0].missing_artifact == "published-prod replay"
    assert review.scope_violations[0].customer_constraint_violated == "no medical advice"

    # Minimal verdict-only payload still validates.
    minimal = TwinUpdatePlanReview(verdict="pass")
    assert minimal.pcm_layer_findings == []


def test_twin_update_implement_review_has_signoff_axes_claim() -> None:
    """The implement-review schema must surface the signoff axes claim and
    PCM-layer regression list.
    """
    from llm_client.workflow.profiles.twin_update import (
        PcmLayerRegression,
        SignoffAxesClaim,
        TwinUpdateImplementReview,
    )

    review = TwinUpdateImplementReview(
        verdict="revise",
        pcm_layer_regressions=[
            PcmLayerRegression(
                layer="Reasoning",
                regression="answer depth shortened across topics",
                severity="warn",
                evidence_path="diff:llm_client/foo.py:1",
            )
        ],
        signoff_axes_claim=SignoffAxesClaim(
            axis_b="not_claimed",
            axis_b_prompt="prompt_dev_smoke_only",
            axis_c="candidate_fix",
            overclaim_risk=True,
            reason="evals passed but no published-prod replay",
        ),
        published_prod_qa_evidence_path="",
    )
    assert review.pcm_layer_regressions[0].layer == "Reasoning"
    assert review.signoff_axes_claim is not None
    assert review.signoff_axes_claim.overclaim_risk is True


def test_pcm_layer_finding_requires_evidence_path() -> None:
    """Groundedness rule: no ungrounded PCM findings."""
    import pydantic
    from llm_client.workflow.profiles.twin_update import PcmLayerFinding

    with pytest.raises(pydantic.ValidationError, match="evidence_path"):
        PcmLayerFinding(layer="Voice", finding="x")  # type: ignore[call-arg]


def test_twin_update_addendum_mentions_pcm_layers_and_rubric() -> None:
    """Reviewer prompt addendum must surface PCM layer names and the three
    rubric axis vocabularies so the structured-output model knows what to
    populate.
    """
    family = get_task_family("twin_update")
    addendum = family.plan_review_prompt_addendum

    # All 5 PCM layer names appear.
    for layer in ("Knowledge", "Voice", "Reasoning", "Values and Boundaries", "Emotional"):
        assert layer in addendum, f"PCM layer {layer!r} missing from plan addendum"

    # Axis vocabularies appear.
    for axis_value in ("regression_signal_only", "prod_verified", "prompt_prod_cleared", "candidate_fix"):
        assert axis_value in addendum, f"rubric value {axis_value!r} missing from plan addendum"

    impl_addendum = family.implement_review_prompt_addendum
    assert "signoff_axes_claim" in impl_addendum
    assert "Reasoning" in impl_addendum  # PCM layer mention in impl too


def test_twin_update_context_loader_reads_task_extras() -> None:
    """The context loader must render the documented task['extra'] keys
    as labeled blocks.
    """
    from llm_client.workflow.profiles.twin_update import _load_twin_context_pack

    task = {
        "extra": {
            "customer": "tony",
            "ai": "genius",
            "ticket_id": "STENO-1234",
            "complaint_text": "Voice feels flat",
            "customer_constraints": ["no medical advice", "no political takes"],
            "published_prod_qa_artifact_path": "customer_files/tony/QA.yaml",
        }
    }
    blocks = _load_twin_context_pack(task)
    assert blocks["Customer twin"] == "customer=tony ai=genius"
    assert blocks["Linear ticket"] == "STENO-1234"
    assert blocks["Customer complaint"] == "Voice feels flat"
    assert "no medical advice" in blocks["Customer constraints"]
    assert blocks["Published-prod QA artifact"] == "customer_files/tony/QA.yaml"


def test_twin_update_context_loader_handles_empty_extras() -> None:
    """No ``extra`` dict (or empty one) should not raise; just return empty."""
    from llm_client.workflow.profiles.twin_update import _load_twin_context_pack

    assert _load_twin_context_pack({}) == {}
    assert _load_twin_context_pack({"extra": {}}) == {}
