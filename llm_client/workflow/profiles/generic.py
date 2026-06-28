"""The ``generic`` duet profile — encodes today's behavior as an explicit profile.

This is what the chassis used before Plan #31 introduced ``TaskFamily``.
Keeping it as a registered profile (rather than hardcoded fallback) means
the chassis can always resolve via the registry and there is no "no profile"
code path to maintain.
"""

from __future__ import annotations

from llm_client.workflow.duet import ImplementReview, PlanReview
from llm_client.workflow.duet_base import TaskFamily
from llm_client.workflow.duet_registry import register_task_family

GENERIC_PROFILE = TaskFamily(
    name="generic",
    plan_review_schema=PlanReview,
    implement_review_schema=ImplementReview,
    plan_prompt_addendum="",
    plan_review_prompt_addendum="",
    implement_prompt_addendum="",
    implement_review_prompt_addendum="",
)


register_task_family(GENERIC_PROFILE)
