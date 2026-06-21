"""Optional LangGraph integration for multi-stage LLM workflows.

Provides a thin integration layer between LangGraph (state, checkpoints,
interrupts) and llm_client (calls, prompts, budgets, observability).

Requires: ``pip install llm-client[workflow]``

Usage::

    from llm_client.workflow import WorkflowContext, WorkflowConfig, build_workflow

    config = WorkflowConfig.from_yaml("config/pipeline.yaml")
    app = build_workflow(
        state_schema=MyState,
        config=config,
        nodes={"stage_a": my_node_fn, ...},
        edges=[("stage_a", "stage_b")],
    )
    result = app.invoke(initial_state)
"""

from llm_client.workflow.config import StageConfig, StageRetryConfig, WorkflowConfig
from llm_client.workflow.context import WorkflowContext
from llm_client.workflow.duet_base import (
    ImplementReviewBase,
    PlanReviewBase,
    TaskFamily,
)
from llm_client.workflow.duet_registry import (
    get_task_family,
    list_task_families,
    register_task_family,
)
from llm_client.workflow.adversarial_review import (
    AdversarialReview,
    AdversarialReviewV1,
    ReviewAnnotation,
    ReviewProfile,
    adversarial_review_schema,
    build_review_prompt,
    get_review_profile,
    list_review_profiles,
    register_review_profile,
    render_quality_optimal_sections,
    resolve_review_schema_version,
)
from llm_client.workflow.review_cycle import (
    ActionableClassification,
    ActionableFinding,
    BudgetLedger,
    BudgetLedgerEntry,
    ReviewCycleSignoff,
    ReviewCycleTask,
    ReviewCallResult,
    ReviewCycleError,
    SkippedFinding,
    actionable_finding_digest,
    build_artifact_index,
    classify_actionable_findings,
    run_review_cycle,
)

# Side-effect import: registers built-in profiles ("generic", "plan_doc_review").
from llm_client.workflow import profiles as _profiles  # noqa: F401

__all__ = [
    "StageConfig",
    "StageRetryConfig",
    "WorkflowConfig",
    "WorkflowContext",
    "PlanReviewBase",
    "ImplementReviewBase",
    "TaskFamily",
    "get_task_family",
    "list_task_families",
    "register_task_family",
    "AdversarialReview",
    "AdversarialReviewV1",
    "ReviewAnnotation",
    "ReviewProfile",
    "adversarial_review_schema",
    "build_review_prompt",
    "get_review_profile",
    "list_review_profiles",
    "register_review_profile",
    "render_quality_optimal_sections",
    "resolve_review_schema_version",
    "ActionableClassification",
    "ActionableFinding",
    "BudgetLedger",
    "BudgetLedgerEntry",
    "ReviewCycleSignoff",
    "ReviewCycleTask",
    "ReviewCallResult",
    "ReviewCycleError",
    "SkippedFinding",
    "actionable_finding_digest",
    "build_artifact_index",
    "classify_actionable_findings",
    "run_review_cycle",
]

# build_workflow is imported lazily to avoid requiring langgraph at import time
# when only config/context is needed
try:
    from llm_client.workflow.builder import build_workflow  # noqa: F401
    __all__.append("build_workflow")
except ImportError:
    pass

# Duet schemas are pure-Pydantic so they import without langgraph. The
# build_duet_workflow() entrypoint itself imports build_workflow lazily.
# noqa block: ruff doesn't see __all__.extend() below, but every name here
# is part of the documented public API surface.
from llm_client.workflow.duet import (  # noqa: F401
    CorrectnessFinding,
    DuetRoles,
    DuetSignoff,
    DuetState,
    DuetTask,
    DuetVerdict,
    ImplementArtifact,
    ImplementCommit,
    ImplementDecision,
    ImplementDeviation,
    ImplementFileChange,
    ImplementReview,
    PlanArtifact,
    PlanReview,
    PlanReviewBlocker,
    PlanStepAtom,
)

__all__.extend([
    "CorrectnessFinding",
    "DuetRoles",
    "DuetSignoff",
    "DuetState",
    "DuetTask",
    "DuetVerdict",
    "ImplementArtifact",
    "ImplementCommit",
    "ImplementDecision",
    "ImplementDeviation",
    "ImplementFileChange",
    "ImplementReview",
    "PlanArtifact",
    "PlanReview",
    "PlanReviewBlocker",
    "PlanStepAtom",
])

try:
    from llm_client.workflow.duet import build_duet_workflow  # noqa: F401
    __all__.append("build_duet_workflow")
except ImportError:
    pass
