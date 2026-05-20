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

__all__ = [
    "StageConfig",
    "StageRetryConfig",
    "WorkflowConfig",
    "WorkflowContext",
]

# build_workflow is imported lazily to avoid requiring langgraph at import time
# when only config/context is needed
try:
    from llm_client.workflow.builder import build_workflow
    __all__.append("build_workflow")
except ImportError:
    pass

# Duet schemas are pure-Pydantic so they import without langgraph. The
# build_duet_workflow() entrypoint itself imports build_workflow lazily.
from llm_client.workflow.duet import (
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
    from llm_client.workflow.duet import build_duet_workflow
    __all__.append("build_duet_workflow")
except ImportError:
    pass
