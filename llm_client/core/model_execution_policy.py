"""Fail-closed model execution policy shared by all LLM runtimes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client.core.errors import LLMConfigurationError

ModelPolicyMode = Literal["enforce_allowlist"]

DEFAULT_EXECUTION_MODEL = "openrouter/deepseek/deepseek-v4-flash"

# Exact canonical routes only. Provider aliases are canonicalized before this
# list is evaluated. Adding a route is a reviewed source change, not a project
# configuration option.
ALLOWED_EXECUTION_MODELS: frozenset[str] = frozenset(
    {
        DEFAULT_EXECUTION_MODEL,
        "openrouter/deepseek/deepseek-chat",
        "openrouter/inception/mercury-2",
        "openrouter/minimax/minimax-m3",
        "openrouter/openai/gpt-5",
        "openrouter/openai/gpt-5-nano",
        "openrouter/openai/gpt-5.4-nano",
        "openrouter/openai/gpt-5.5",
        "openrouter/openai/gpt-5.6-luna",
        "openrouter/openai/gpt-5.6-terra",
        "openrouter/google/gemini-3.1-pro-preview",
        "openrouter/qwen/qwen3.7-max",
        "openrouter/x-ai/grok-4.5",
        "openrouter/z-ai/glm-5.2",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-3-flash-preview",
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.6",
        "gpt-5.6-terra",
        "codex",
        "codex/gpt-5.4",
        "claude-code",
        "claude-code/sonnet",
    }
)


class ModelExecutionDecision(BaseModel):
    """Trace-safe result of evaluating one complete model chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ModelPolicyMode
    enforced: bool
    default_model: str
    selected_models: list[str]
    uses_only_default: bool
    justification: str | None = Field(
        default=None,
        description="Caller-recorded reason for selecting any allowed non-default route.",
    )


def evaluate_model_execution_policy(
    models: list[str],
    *,
    mode: str = "enforce_allowlist",
    justification: str | None = None,
) -> ModelExecutionDecision:
    """Validate a canonical model chain and return its durable policy decision."""

    if mode != "enforce_allowlist":
        raise LLMConfigurationError(
            "model_policy must be 'enforce_allowlist'; compatibility mode was removed"
        )
    normalized_justification = (
        str(justification).strip() if justification is not None else None
    )
    if normalized_justification == "":
        raise LLMConfigurationError(
            "model_justification must be non-empty when provided"
        )
    selected = [str(model).strip() for model in models]
    if not selected or any(not model for model in selected):
        raise LLMConfigurationError("model execution policy requires a model")

    uses_only_default = all(model == DEFAULT_EXECUTION_MODEL for model in selected)
    disallowed = [model for model in selected if model not in ALLOWED_EXECUTION_MODELS]
    if disallowed:
        raise LLMConfigurationError(
            "model is not in the llm_client execution allowlist: "
            + ", ".join(disallowed)
        )
    if not uses_only_default and normalized_justification is None:
        raise LLMConfigurationError(
            "allowed non-default models require model_justification"
        )

    return ModelExecutionDecision(
        mode=mode,
        enforced=True,
        default_model=DEFAULT_EXECUTION_MODEL,
        selected_models=selected,
        uses_only_default=uses_only_default,
        justification=normalized_justification,
    )
