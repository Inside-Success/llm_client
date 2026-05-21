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

    _reset_for_tests()
    yield
    _reset_for_tests()
    register_task_family(GENERIC_PROFILE)
    register_task_family(PLAN_DOC_REVIEW_PROFILE)


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
