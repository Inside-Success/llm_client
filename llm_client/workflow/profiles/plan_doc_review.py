"""The ``plan_doc_review`` duet profile.

Specialized for critiquing plan documents against the repository's
``docs/plans/TEMPLATE.md`` structure (Gap / References Reviewed / Files Affected
/ Plan / Required Tests / Acceptance Criteria / Notes). Adds reviewer fields
the generic schema lost fidelity on during Plan #29's self-review:

- ``template_section_misses`` — sections from TEMPLATE.md the plan omits.
- ``references_unverified`` — cited ``file:line`` ranges the reviewer could not
  open or whose claimed content could not be confirmed.
- ``acceptance_criteria_unmeasurable`` — criteria that are present but not
  testable as written (distinct from "missing acceptance check").

The implementation-review side reuses the generic ``ImplementReview``: a
plan-doc revision implementation looks like a regular code review at that
layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm_client.workflow.duet import ImplementReview, PlanReview
from llm_client.workflow.duet_base import TaskFamily
from llm_client.workflow.duet_registry import register_task_family


class CitationRef(BaseModel):
    """A ``file:line`` (or ``file:LL-LL``) citation that the reviewer could not verify."""

    cited_as: str
    reason_unverified: str = ""


class PlanDocPlanReview(PlanReview):
    """Plan reviewer schema specialized for plan-doc critique.

    Extends ``PlanReview`` so existing chassis behavior (router on ``verdict``,
    persistence to ``plan_review.json``, etc.) keeps working. Adds three
    plan-doc-specific findings buckets.
    """

    template_section_misses: list[str] = Field(default_factory=list)
    references_unverified: list[CitationRef] = Field(default_factory=list)
    acceptance_criteria_unmeasurable: list[str] = Field(default_factory=list)


_PLAN_REVIEW_ADDENDUM = (
    "\n\n## Plan-doc review extension\n"
    "This is a plan-doc-level review against the repo's docs/plans/TEMPLATE.md "
    "structure. In addition to the generic PlanReview fields:\n"
    "- template_section_misses: list any of these TEMPLATE.md sections that "
    "the plan omits or empties out: Gap, References Reviewed, Files Affected, "
    "Plan, Required Tests, Acceptance Criteria, Notes.\n"
    "- references_unverified: list every cited file:line (or file:LL-LL) range "
    "you could not open or whose claimed content you could not confirm. "
    "Use the CitationRef shape {cited_as, reason_unverified}.\n"
    "- acceptance_criteria_unmeasurable: list any acceptance criterion that "
    "is present but not testable as written (distinct from missing_acceptance_checks "
    "which is about absence).\n"
    "Blockers still require evidence_path; nits remain free-form."
)


PLAN_DOC_REVIEW_PROFILE = TaskFamily(
    name="plan_doc_review",
    plan_review_schema=PlanDocPlanReview,
    implement_review_schema=ImplementReview,  # generic impl review is fine for plan-doc revisions
    plan_prompt_addendum="",
    plan_review_prompt_addendum=_PLAN_REVIEW_ADDENDUM,
    implement_prompt_addendum="",
    implement_review_prompt_addendum="",
)


register_task_family(PLAN_DOC_REVIEW_PROFILE)
