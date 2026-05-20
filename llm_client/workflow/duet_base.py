"""Base schemas and the TaskFamily extension point for the duet chassis.

The duet workflow runs a generic chassis (LangGraph wiring, conditional routers,
cycle gating, artifact persistence) that should not change when a domain wants
its own reviewer fields, prompt framing, or context loader. ``TaskFamily``
captures everything a domain owns; the chassis owns the rest.

``PlanReviewBase`` / ``ImplementReviewBase`` declare the minimum contract that
any reviewer schema must honor: a router-grade ``verdict`` plus the
``reviewer_summary`` / ``reviewer_model`` fields used by observability and the
signoff artifact. Domain profiles subclass these and add fields; the router
only branches on ``verdict``, so subclass additions don't break control flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel

DuetVerdict = Literal["pass", "revise", "block"]


class PlanReviewBase(BaseModel):
    """Minimum contract for any plan-reviewer schema.

    Subclasses can add domain-specific fields (e.g. ``template_section_misses``
    for plan-doc review, ``pcm_layer_findings`` for twin-update review). The
    chassis router only consumes ``verdict``, so subclass additions are safe.
    """

    verdict: DuetVerdict
    reviewer_summary: str = ""
    reviewer_model: str = ""


class ImplementReviewBase(BaseModel):
    """Minimum contract for any implementation-reviewer schema.

    Same router-grade ``verdict`` contract as ``PlanReviewBase``. Domain
    profiles add fields like ``contract_violations`` against domain-specific
    constraints, or ``test_coverage_findings`` for code-heavy reviews.
    """

    verdict: DuetVerdict
    reviewer_summary: str = ""
    reviewer_model: str = ""


def _empty_context_loader(task: dict[str, Any]) -> dict[str, str]:
    """Default ``TaskFamily.context_loader`` — contributes no extra blocks."""
    return {}


@dataclass(frozen=True)
class TaskFamily:
    """A registered duet profile.

    Profiles let domains plug in their own reviewer schemas, prompt addenda,
    and context loaders without forking the chassis. Use the registry
    (``register_task_family`` / ``get_task_family``) to look up by name.

    Attributes:
        name: Stable identifier the chassis and CLI resolve by.
        plan_review_schema: Pydantic class for plan reviewer output; must
            extend ``PlanReviewBase`` so the router can read ``verdict``.
        implement_review_schema: Same contract for implementation reviewer.
        plan_prompt_addendum: Extra text appended to the plan-implementer's
            user message after the chassis's base prompt.
        plan_review_prompt_addendum: Extra text for the plan reviewer.
        implement_prompt_addendum: Extra text for the implementer.
        implement_review_prompt_addendum: Extra text for the impl reviewer.
        context_loader: Callable that receives the task dict and returns
            ``{label: rendered_content}`` blocks the chassis renders as
            ``## <label>`` sections before the addendum.
    """

    name: str
    plan_review_schema: type[PlanReviewBase]
    implement_review_schema: type[ImplementReviewBase]
    plan_prompt_addendum: str = ""
    plan_review_prompt_addendum: str = ""
    implement_prompt_addendum: str = ""
    implement_review_prompt_addendum: str = ""
    context_loader: Callable[[dict[str, Any]], dict[str, str]] = field(
        default=_empty_context_loader
    )


__all__ = [
    "DuetVerdict",
    "PlanReviewBase",
    "ImplementReviewBase",
    "TaskFamily",
]
