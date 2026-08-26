"""Task-based model selection helpers for downstream projects.

This gives projects one small happy path for model governance:

1. resolve a model from the shared task registry,
2. optionally honor an explicit override,
3. enforce deprecated-model blocking in strict lanes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client.core.models import get_model


class ResolvedModelSelection(BaseModel):
    """Resolved model selection metadata."""

    task: str
    model: str
    source: Literal["task", "override"]
    strict_models: bool = True


class ResolvedModelChain(BaseModel):
    """Resolved primary model plus any fallback models."""

    primary: ResolvedModelSelection
    fallback_models: list[str] = Field(default_factory=list)
    fallback_tasks: list[str] = Field(default_factory=list)


WorkloadEnvironment = Literal[
    "interactive",
    "trusted_private_automation",
    "managed_automation",
    "service",
]
SubscriptionCapacity = Literal["available", "exhausted", "unknown"]
PaidOverflowRoute = Literal["codex_credits", "openai_api", "openrouter"]
WorkloadRouteProvider = Literal[
    "codex_subscription",
    "codex_credits",
    "openai_api",
    "openrouter",
]


class WorkloadRouteContext(BaseModel):
    """Declared routing facts required before choosing a provider route.

    The fields intentionally have no operational defaults. A caller must state
    whether the workload fits Codex, whether included capacity is available,
    and whether an API or OpenRouter-specific requirement applies.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_compatible: bool
    environment: WorkloadEnvironment
    subscription_auth_supported: bool
    subscription_capacity: SubscriptionCapacity
    requires_openai_api_contract: bool
    requires_openrouter_features: bool
    openrouter_is_live_best_value: bool
    paid_overflow_route: PaidOverflowRoute | None = None


class ResolvedWorkloadRoute(BaseModel):
    """One explicit provider/model selection with a traceable reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: WorkloadRouteProvider
    model: str
    model_justification: str
    reasoning_effort: Literal["medium"] = "medium"


def resolve_workload_route(context: WorkloadRouteContext) -> ResolvedWorkloadRoute:
    """Choose a route from declared workload compatibility and constraints.

    Codex subscription capacity is selected only for compatible interactive or
    trusted-private work with supported subscription authentication and known
    available included capacity. This selector never treats OpenRouter as an
    automatic quota-overflow route: exhaustion requires a declared paid route.
    """

    if (
        context.requires_openai_api_contract
        and context.requires_openrouter_features
    ):
        raise ValueError(
            "OpenAI API contract and OpenRouter-specific requirements conflict; "
            "split the workload or declare one supported boundary"
        )
    if context.requires_openrouter_features:
        return ResolvedWorkloadRoute(
            provider="openrouter",
            model="openrouter/openai/gpt-5.6-luna",
            model_justification=(
                "Workload requires an OpenRouter-specific capability such as "
                "non-OpenAI model access, multi-provider routing, or provider controls."
            ),
        )
    if context.openrouter_is_live_best_value:
        return ResolvedWorkloadRoute(
            provider="openrouter",
            model="openrouter/openai/gpt-5.6-luna",
            model_justification=(
                "A current, workload-specific price and capacity comparison "
                "selects OpenRouter over the direct alternatives."
            ),
        )
    if (
        context.requires_openai_api_contract
        or context.environment in {"managed_automation", "service"}
    ):
        return ResolvedWorkloadRoute(
            provider="openai_api",
            model="gpt-5.6",
            model_justification=(
                "Workload requires direct OpenAI API authentication, service "
                "semantics, concurrency, or automation support."
            ),
        )
    if (
        context.codex_compatible
        and context.subscription_auth_supported
        and context.subscription_capacity == "available"
        and context.environment
        in {"interactive", "trusted_private_automation"}
    ):
        return ResolvedWorkloadRoute(
            provider="codex_subscription",
            model="codex/gpt-5.6-luna",
            model_justification=(
                "Compatible trusted workload has supported subscription auth "
                "and available included Codex capacity."
            ),
        )
    if (
        context.codex_compatible
        and context.subscription_auth_supported
        and context.environment
        in {"interactive", "trusted_private_automation"}
        and context.subscription_capacity == "exhausted"
    ):
        if context.paid_overflow_route is None:
            raise ValueError(
                "Codex capacity is exhausted; declare paid_overflow_route after "
                "comparing Codex credits, direct OpenAI API, and OpenRouter"
            )
        if context.paid_overflow_route == "codex_credits":
            return ResolvedWorkloadRoute(
                provider="codex_credits",
                model="codex/gpt-5.6-luna",
                model_justification=(
                    "Included Codex capacity is exhausted; the recorded live "
                    "comparison selected paid Codex credits."
                ),
            )
        if context.paid_overflow_route == "openrouter":
            return ResolvedWorkloadRoute(
                provider="openrouter",
                model="openrouter/openai/gpt-5.6-luna",
                model_justification=(
                    "Included Codex capacity is exhausted; the recorded live "
                    "comparison selected OpenRouter."
                ),
            )
        return ResolvedWorkloadRoute(
            provider="openai_api",
            model="gpt-5.6",
            model_justification=(
                "Included Codex capacity is exhausted; the recorded live "
                "comparison selected direct OpenAI API."
            ),
        )
    return ResolvedWorkloadRoute(
        provider="openai_api",
        model="gpt-5.6",
        model_justification=(
            "Codex subscription is not applicable or cannot be verified for "
            "this declared workload; use the direct OpenAI API route."
        ),
    )


def resolve_model_selection(
    task: str,
    *,
    override_model: str | None = None,
    strict_models: bool = True,
    available_only: bool = False,
    use_performance: bool = True,
) -> ResolvedModelSelection:
    """Resolve a model for a task, optionally preserving an explicit override."""

    normalized_task = task.strip()
    if not normalized_task:
        raise ValueError("task must be non-empty")
    if override_model:
        return ResolvedModelSelection(
            task=normalized_task,
            model=override_model,
            source="override",
            strict_models=strict_models,
        )
    model = get_model(
        normalized_task,
        available_only=available_only,
        use_performance=use_performance,
    )
    return ResolvedModelSelection(
        task=normalized_task,
        model=model,
        source="task",
        strict_models=strict_models,
    )


def resolve_model_chain(
    task: str,
    *,
    fallback_tasks: list[str] | None = None,
    override_model: str | None = None,
    fallback_models: list[str] | None = None,
    strict_models: bool = True,
    available_only: bool = False,
    use_performance: bool = True,
) -> ResolvedModelChain:
    """Resolve a primary model plus deduplicated fallback models."""

    primary = resolve_model_selection(
        task,
        override_model=override_model,
        strict_models=strict_models,
        available_only=available_only,
        use_performance=use_performance,
    )
    deduped_fallbacks: list[str] = []
    seen_models = {primary.model}
    resolved_fallback_tasks: list[str] = []

    for fallback_task in fallback_tasks or []:
        selection = resolve_model_selection(
            fallback_task,
            strict_models=strict_models,
            available_only=available_only,
            use_performance=use_performance,
        )
        resolved_fallback_tasks.append(selection.task)
        if selection.model in seen_models:
            continue
        deduped_fallbacks.append(selection.model)
        seen_models.add(selection.model)

    for fallback_model in fallback_models or []:
        normalized = fallback_model.strip()
        if not normalized or normalized in seen_models:
            continue
        deduped_fallbacks.append(normalized)
        seen_models.add(normalized)

    return ResolvedModelChain(
        primary=primary,
        fallback_models=deduped_fallbacks,
        fallback_tasks=resolved_fallback_tasks,
    )


@contextmanager
def strict_model_policy(enabled: bool = True) -> Iterator[None]:
    """Temporarily set deprecated-model blocking for a call site."""

    previous = os.environ.get("LLM_CLIENT_STRICT_MODELS")
    if enabled:
        os.environ["LLM_CLIENT_STRICT_MODELS"] = "1"
    else:
        os.environ.pop("LLM_CLIENT_STRICT_MODELS", None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LLM_CLIENT_STRICT_MODELS", None)
        else:
            os.environ["LLM_CLIENT_STRICT_MODELS"] = previous
