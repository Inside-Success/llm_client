"""Fail-closed model execution policy shared by all LLM runtimes."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from llm_client.core.errors import LLMConfigurationError

ModelPolicyMode = Literal["enforce_allowlist"]
ReasoningEffort = Literal[
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]
REASONING_EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)

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
        "openrouter/openai/gpt-5.6-luna",
        "openrouter/openai/gpt-5.6-sol",
        "openrouter/openai/gpt-5.6-terra",
        "openrouter/google/gemini-3.1-pro-preview",
        "openrouter/qwen/qwen3.7-max",
        "openrouter/x-ai/grok-4.5",
        "openrouter/z-ai/glm-5.2",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-3-flash-preview",
        "gpt-5.6",
        "gpt-5.6-terra",
        "codex",
        "codex/gpt-5.4",
        "codex/gpt-5.6-luna",
        "codex/gpt-5.6-terra",
        "claude-code",
        "claude-code/sonnet",
    }
)


class ReasoningCapability(BaseModel):
    """Reviewed explicit-effort contract for one exact execution route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supported_efforts: frozenset[ReasoningEffort]
    mandatory: bool
    observed_default: ReasoningEffort | None = None
    source: str


def _reasoning_capability(
    supported_efforts: set[ReasoningEffort],
    *,
    mandatory: bool,
    observed_default: ReasoningEffort | None,
    source: str,
) -> ReasoningCapability:
    """Build one immutable reviewed capability declaration."""

    return ReasoningCapability(
        supported_efforts=frozenset(supported_efforts),
        mandatory=mandatory,
        observed_default=observed_default,
        source=source,
    )


_OPENROUTER_MODELS_SOURCE = (
    "OpenRouter GET /api/v1/models observed 2026-07-23"
)
_OPENROUTER_GPT56_SOL_SOURCE = (
    "OpenRouter GET /api/v1/models observed 2026-07-25"
)
_OPENAI_MODELS_SOURCE = "OpenAI model documentation observed 2026-07-23"
_LITELLM_GEMINI_SOURCE = (
    "installed LiteLLM provider-free Gemini normalization observed 2026-07-23"
)
_CODEX_SOURCE = "llm_client Codex SDK/CLI adapter contract"

# This is enforcement policy for exact already-allowlisted routes, not a
# transport capability database. Provider SDKs and LiteLLM still own payload
# translation. Routes without an effort-selection surface are intentionally
# absent and remain subject to provider parameter validation.
REASONING_CAPABILITIES: dict[str, ReasoningCapability] = {
    "openrouter/deepseek/deepseek-v4-flash": _reasoning_capability(
        {"none", "high", "xhigh"},
        mandatory=False,
        observed_default="high",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/inception/mercury-2": _reasoning_capability(
        {"none", "low", "medium", "high"},
        mandatory=False,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/openai/gpt-5": _reasoning_capability(
        {"minimal", "low", "medium", "high"},
        mandatory=True,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/openai/gpt-5-nano": _reasoning_capability(
        {"minimal", "low", "medium", "high"},
        mandatory=True,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/openai/gpt-5.4-nano": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh"},
        mandatory=False,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/openai/gpt-5.6-luna": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh", "max"},
        mandatory=False,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/openai/gpt-5.6-sol": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh", "max"},
        mandatory=False,
        observed_default="medium",
        source=_OPENROUTER_GPT56_SOL_SOURCE,
    ),
    "openrouter/openai/gpt-5.6-terra": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh", "max"},
        mandatory=False,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/google/gemini-3.1-pro-preview": _reasoning_capability(
        {"low", "medium", "high"},
        mandatory=True,
        observed_default="medium",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/x-ai/grok-4.5": _reasoning_capability(
        {"low", "medium", "high"},
        mandatory=True,
        observed_default="high",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "openrouter/z-ai/glm-5.2": _reasoning_capability(
        {"none", "high", "xhigh"},
        mandatory=False,
        observed_default="high",
        source=_OPENROUTER_MODELS_SOURCE,
    ),
    "gemini/gemini-2.5-flash": _reasoning_capability(
        {"none", "low", "medium", "high"},
        mandatory=False,
        observed_default=None,
        source=_LITELLM_GEMINI_SOURCE,
    ),
    "gemini/gemini-2.5-flash-lite": _reasoning_capability(
        {"none", "low", "medium", "high"},
        mandatory=False,
        observed_default=None,
        source=_LITELLM_GEMINI_SOURCE,
    ),
    "gemini/gemini-3-flash-preview": _reasoning_capability(
        {"minimal", "low", "medium", "high"},
        mandatory=True,
        observed_default=None,
        source=_LITELLM_GEMINI_SOURCE,
    ),
    "gpt-5.6": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh", "max"},
        mandatory=False,
        observed_default="medium",
        source=_OPENAI_MODELS_SOURCE,
    ),
    "gpt-5.6-terra": _reasoning_capability(
        {"none", "low", "medium", "high", "xhigh", "max"},
        mandatory=False,
        observed_default="medium",
        source=_OPENAI_MODELS_SOURCE,
    ),
    "codex": _reasoning_capability(
        {"low", "medium", "high"},
        mandatory=True,
        observed_default="high",
        source=_CODEX_SOURCE,
    ),
    "codex/gpt-5.4": _reasoning_capability(
        {"low", "medium", "high"},
        mandatory=True,
        observed_default="high",
        source=_CODEX_SOURCE,
    ),
    "codex/gpt-5.6-luna": _reasoning_capability(
        {"low", "medium", "high"},
        mandatory=True,
        observed_default=None,
        source=_CODEX_SOURCE,
    ),
    "codex/gpt-5.6-terra": _reasoning_capability(
        {"medium"},
        mandatory=True,
        observed_default=None,
        source=_CODEX_SOURCE,
    ),
}


class ReasoningPolicyDecision(BaseModel):
    """Trace-safe result of explicit reasoning-policy validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required: bool
    effort: ReasoningEffort | None
    configurable_models: list[str]


def evaluate_reasoning_policy(
    models: list[str],
    *,
    reasoning_effort: str | None,
) -> ReasoningPolicyDecision:
    """Require and validate one explicit effort across a resolved model chain."""

    configurable = [
        model for model in models if model in REASONING_CAPABILITIES
    ]
    if not configurable:
        normalized = (
            str(reasoning_effort).strip().lower()
            if reasoning_effort is not None
            else None
        )
        if normalized is not None and normalized not in REASONING_EFFORTS:
            raise LLMConfigurationError(
                f"unknown reasoning_effort={reasoning_effort!r}; "
                f"allowed: {', '.join(sorted(REASONING_EFFORTS))}"
            )
        return ReasoningPolicyDecision(
            required=False,
            effort=cast(ReasoningEffort | None, normalized),
            configurable_models=[],
        )

    if reasoning_effort is None or not str(reasoning_effort).strip():
        defaults = ", ".join(
            f"{model}={REASONING_CAPABILITIES[model].observed_default or 'unknown'}"
            for model in configurable
        )
        raise LLMConfigurationError(
            "reasoning_effort is required for configurable reasoning models; "
            "use reasoning_effort='none' for explicit off where supported. "
            f"Provider defaults are forbidden ({defaults})"
        )

    normalized = str(reasoning_effort).strip().lower()
    for model in configurable:
        capability = REASONING_CAPABILITIES[model]
        if normalized not in capability.supported_efforts:
            allowed = ", ".join(sorted(capability.supported_efforts))
            if normalized == "none" and capability.mandatory:
                raise LLMConfigurationError(
                    f"reasoning_effort='none' is forbidden for mandatory-reasoning "
                    f"model {model}; allowed: {allowed}"
                )
            raise LLMConfigurationError(
                f"reasoning_effort={reasoning_effort!r} is unsupported for {model}; "
                f"allowed: {allowed}"
            )

    return ReasoningPolicyDecision(
        required=True,
        effort=cast(ReasoningEffort, normalized),
        configurable_models=configurable,
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
    reasoning_policy: ReasoningPolicyDecision


def evaluate_model_execution_policy(
    models: list[str],
    *,
    mode: str = "enforce_allowlist",
    justification: str | None = None,
    reasoning_effort: str | None = None,
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
    reasoning_policy = evaluate_reasoning_policy(
        selected,
        reasoning_effort=reasoning_effort,
    )

    return ModelExecutionDecision(
        mode=cast(ModelPolicyMode, mode),
        enforced=True,
        default_model=DEFAULT_EXECUTION_MODEL,
        selected_models=selected,
        uses_only_default=uses_only_default,
        justification=normalized_justification,
        reasoning_policy=reasoning_policy,
    )
