"""Pre-call contract helpers for ``llm_client``.

This module centralizes the invariants that must hold before any provider or
agent SDK dispatch happens:

1. every call has a resolved ``task``,
2. every call has a resolved ``trace_id``,
3. every call has a pre-flight budget check,
4. prompt asset provenance is validated before it enters observability,
5. retry-safety policy is derived consistently for agent SDK calls,
6. execution-mode and model/kwargs capability validation,
7. unsupported-param coercion, agent-only kwargs filtering,
8. model deprecation warnings and empty-response error classification,
9. declared prompt-size ceilings are measured before dispatch.

These checks belong to the runtime substrate itself, not to any one transport
backend. Keeping them in one module makes the boundary easier to reason about
and easier to test without dragging the full client runtime with it.
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
import threading
import uuid
from typing import Any, Literal, NoReturn

import litellm
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import llm_client.io_log as _io_log
from llm_client.core.errors import (
    DeprecatedModelError,
    LLMBudgetExceededError,
    LLMCapabilityError,
    LLMEmptyResponseError,
    LLMModelNotFoundError,
    LLMPromptBudgetExceededError,
)
from llm_client.observability.budget_reservations import (
    BudgetReservationLease,
    acquire_budget_reservation,
    release_tracked_budget_reservation,
    settle_tracked_budget_reservation,
    track_budget_reservation,
)
from llm_client.core.model_detection import (
    _base_model_name,
    _is_responses_api_model,
)
from llm_client.prompt_assets import parse_prompt_ref

logger = logging.getLogger(__name__)

# A scope is a request-level budget boundary.  Settled cost alone cannot make
# concurrent child dispatch safe: both children could observe the same spend
# before either has a terminal cost row.  Public calls therefore hold this
# process-local lease for the duration of a scoped call.  Cross-process budget
# coordination is intentionally not claimed by this lightweight client control.
_active_budget_scopes: set[str] = set()
_budget_scope_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Tag / budget / retry-safety contracts (original surface)
# ---------------------------------------------------------------------------

REQUIRE_TAGS_ENV = "LLM_CLIENT_REQUIRE_TAGS"
AGENT_RETRY_SAFE_ENV = "LLM_CLIENT_AGENT_RETRY_SAFE"


class StructuredOutputPolicy(BaseModel):
    """Select which structured-output execution paths a logical call may use.

    Auto mode preserves the historical native-schema-to-Instructor routing.
    Strict mode requires provider-native JSON schema and fails loudly rather
    than changing execution mechanisms when capability checks or the provider
    reject that schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["auto", "require_native_json_schema"] = Field(
        default="auto",
        description="Allowed structured-output execution paths for this logical call.",
    )


class ObservabilityContentPolicy(BaseModel):
    """Control durable content retention for one structured logical call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["full", "metadata_only"] = Field(
        default="full",
        description=(
            "Whether durable call observability may include prompt/response content "
            "and replay snapshots. metadata_only retains bounded operational metadata."
        ),
    )


class OpenRouterRoutePolicyV1(BaseModel):
    """Typed intent compiled into OpenRouter routing and cache controls.

    Route fields describe caller-authorized provider constraints. Response-cache
    fields explicitly authorize OpenRouter to retain and reuse an exact response;
    they are disabled by default and are incompatible with zero-data-retention.
    This contract does not claim a local inventory of live providers or endpoints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_providers: tuple[str, ...] | None = None
    ignored_providers: tuple[str, ...] | None = None
    data_collection: Literal["allow", "deny"] | None = None
    zero_data_retention: bool | None = None
    allow_provider_fallbacks: bool = True
    sort: Literal["price", "throughput", "latency"] | None = None
    require_parameters: Literal[True] = True
    response_cache_mode: Literal["disabled", "enabled", "refresh"] = "disabled"
    response_cache_ttl_seconds: int | None = Field(default=None, gt=0, le=86_400)

    @field_validator("allowed_providers", "ignored_providers")
    @classmethod
    def normalize_provider_names(
        cls, value: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if value is None:
            return None
        return tuple(
            provider.strip() if isinstance(provider, str) else provider
            for provider in value
        )

    @model_validator(mode="after")
    def validate_constraints(self) -> "OpenRouterRoutePolicyV1":
        normalized_sets: dict[str, set[str]] = {}
        for field_name, providers in (
            ("allowed_providers", self.allowed_providers),
            ("ignored_providers", self.ignored_providers),
        ):
            if providers is None:
                continue
            if not providers:
                raise ValueError(f"{field_name} must not be empty when provided")
            normalized: set[str] = set()
            for provider in providers:
                if not isinstance(provider, str) or not provider.strip():
                    raise ValueError(
                        f"{field_name} entries must be non-empty strings"
                    )
                key = provider.casefold()
                if key in normalized:
                    raise ValueError(f"{field_name} must not contain duplicates")
                normalized.add(key)
            normalized_sets[field_name] = normalized
        overlap = normalized_sets.get("allowed_providers", set()) & normalized_sets.get(
            "ignored_providers", set()
        )
        if overlap:
            raise ValueError("allowed_providers and ignored_providers must not overlap")
        if self.data_collection == "allow" and self.zero_data_retention is True:
            raise ValueError(
                "data_collection='allow' conflicts with zero_data_retention=True"
            )
        if self.response_cache_mode in {"enabled", "refresh"} and self.zero_data_retention is True:
            raise ValueError(
                "response_cache_mode='enabled' conflicts with zero_data_retention=True"
            )
        if (
            self.response_cache_ttl_seconds is not None
            and self.response_cache_mode not in {"enabled", "refresh"}
        ):
            raise ValueError(
                "response_cache_ttl_seconds requires response_cache_mode='enabled' "
                "or 'refresh'"
            )
        return self


def truthy_env(value: Any) -> bool:
    """Parse common truthy env-style values."""
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def tags_strict_mode(task: str | None) -> bool:
    """Whether missing task/trace/budget tags should raise instead of defaulting."""
    if truthy_env(os.environ.get(REQUIRE_TAGS_ENV)):
        return True
    if truthy_env(os.environ.get("CI")):
        return True
    normalized_task = str(task or "").strip().lower()
    return normalized_task.startswith(("benchmark", "bench", "eval", "ci"))


def normalize_prompt_ref(prompt_ref: str | None) -> str | None:
    """Validate prompt asset identity before it enters observability."""
    if prompt_ref is None:
        return None
    normalized = str(prompt_ref).strip()
    if not normalized:
        raise ValueError("prompt_ref must not be empty when provided.")
    return parse_prompt_ref(normalized).prompt_ref


def require_tags(
    task: str | None,
    trace_id: str | None,
    max_budget: float | None,
    *,
    caller: str,
) -> tuple[str, str, float, list[str]]:
    """Resolve observability tags and enforce shared guardrails.

    In strict mode, missing values fail loudly. Outside strict mode, the
    substrate fills in conservative defaults and emits warnings so the call is
    still observable and queryable.
    """
    missing: list[str] = []
    if not task:
        missing.append("task")
    if not trace_id:
        missing.append("trace_id")
    if max_budget is None:
        missing.append("max_budget")

    if tags_strict_mode(task) and missing:
        raise ValueError(
            f"Missing required kwargs: {', '.join(missing)}. "
            "Strict tag enforcement is enabled "
            f"(set {REQUIRE_TAGS_ENV}=0 to disable outside CI/benchmark)."
        )

    resolved_task = str(task).strip() if task else "adhoc"
    resolved_trace_id = (
        str(trace_id).strip() if trace_id else f"auto/{caller}/{uuid.uuid4().hex[:12]}"
    )
    if max_budget is None:
        resolved_max_budget = 0.0
    else:
        try:
            resolved_max_budget = float(max_budget)
        except (TypeError, ValueError):
            raise ValueError(f"max_budget must be numeric, got {max_budget!r}") from None

    auto_warnings: list[str] = []
    if not task:
        auto_warnings.append("AUTO_TAG: task=adhoc")
    if not trace_id:
        auto_warnings.append(f"AUTO_TAG: trace_id={resolved_trace_id}")
    if max_budget is None:
        auto_warnings.append("AUTO_TAG: max_budget=0 (unlimited)")

    _io_log.enforce_feature_profile(resolved_task, caller="llm_client.core.client")
    _io_log.enforce_experiment_context(resolved_task, caller="llm_client.core.client")
    return resolved_task, resolved_trace_id, resolved_max_budget, auto_warnings


def check_budget(
    trace_id: str,
    max_budget: float,
    *,
    reservation: float = 0.0,
    budget_scope_trace_id: str | None = None,
    warning_sink: list[str] | None = None,
) -> None:
    """Block a dispatch when exact or scoped spend plus reserve exceeds budget."""
    scope = resolve_budget_scope(trace_id, budget_scope_trace_id)
    if max_budget <= 0:
        return
    if reservation < 0:
        raise ValueError("budget reservation must be non-negative")
    spent = (
        _io_log.get_cost(trace_prefix=scope)
        if scope is not None
        else _io_log.get_cost(trace_id=trace_id)
    )
    budget_label = f"budget scope {scope}" if scope is not None else f"trace {trace_id}"
    if spent >= max_budget:
        raise LLMBudgetExceededError(
            f"Budget exceeded for {budget_label}: "
            f"${spent:.4f} spent >= ${max_budget:.4f} limit"
        )
    if spent + reservation > max_budget:
        raise LLMBudgetExceededError(
            f"Budget reservation exceeds {budget_label} limit: "
            f"${spent:.4f} spent + ${reservation:.4f} reserve > ${max_budget:.4f} limit"
        )
    if warning_sink is None:
        return
    ratio = spent / max_budget
    if ratio >= 0.8:
        threshold = 80
    elif ratio >= 0.5:
        threshold = 50
    else:
        return
    warning_sink.append(
        f"BUDGET_WARNING: {budget_label} has spent ${spent:.4f} "
        f"({ratio:.0%}) of its ${max_budget:.4f} budget; {threshold}% threshold reached"
    )


def resolve_budget_scope(
    trace_id: str,
    budget_scope_trace_id: str | None,
) -> str | None:
    """Validate an optional root trace whose descendants share one budget."""

    if budget_scope_trace_id is None:
        return None
    if not isinstance(budget_scope_trace_id, str) or not budget_scope_trace_id.strip():
        raise ValueError("budget_scope_trace_id must be a non-empty string when provided.")
    scope = budget_scope_trace_id.strip()
    if trace_id != scope and not trace_id.startswith(scope + "/"):
        raise ValueError(
            "budget_scope_trace_id must equal trace_id or be its slash-delimited ancestor: "
            f"scope={scope!r}, trace_id={trace_id!r}."
        )
    return scope


def acquire_budget_scope(
    trace_id: str,
    max_budget: float,
    *,
    reservation: float = 0.0,
    budget_scope_trace_id: str | None = None,
    budget_scope_mode: Literal["sequential", "reserved_concurrent"] = "sequential",
    warning_sink: list[str] | None = None,
) -> str | BudgetReservationLease | None:
    """Admit one bounded scoped call and return its lease token.

    A scoped budget is deliberately sequential within one process.  This
    prevents sibling calls from independently passing a settled-cost check
    before either one records its final cost.  Callers must release a returned
    token at every terminal boundary.
    """

    if budget_scope_mode not in {"sequential", "reserved_concurrent"}:
        raise ValueError(f"unknown budget_scope_mode: {budget_scope_mode!r}")
    scope = resolve_budget_scope(trace_id, budget_scope_trace_id)
    if budget_scope_mode == "reserved_concurrent":
        if scope is None:
            raise ValueError("reserved_concurrent requires budget_scope_trace_id")
        if max_budget <= 0:
            raise ValueError("reserved_concurrent requires max_budget > 0")
        lease = acquire_budget_reservation(
            scope_trace_id=scope,
            call_trace_id=trace_id,
            max_budget=max_budget,
            reservation=reservation,
        )
        track_budget_reservation(lease)
        return lease
    if scope is None or max_budget <= 0:
        check_budget(
            trace_id,
            max_budget,
            reservation=reservation,
            budget_scope_trace_id=scope,
            warning_sink=warning_sink,
        )
        return None
    with _budget_scope_lock:
        if scope in _active_budget_scopes:
            raise LLMBudgetExceededError(
                f"Budget scope {scope} already has an in-flight call; "
                "scoped calls must complete sequentially."
            )
        check_budget(
            trace_id,
            max_budget,
            reservation=reservation,
            budget_scope_trace_id=scope,
            warning_sink=warning_sink,
        )
        _active_budget_scopes.add(scope)
    return scope


def release_budget_scope(lease: str | BudgetReservationLease | None) -> None:
    """Release a lease returned by :func:`acquire_budget_scope`."""

    if lease is None:
        return
    if isinstance(lease, BudgetReservationLease):
        release_tracked_budget_reservation(lease)
        return
    with _budget_scope_lock:
        _active_budget_scopes.discard(lease)


def settle_budget_scope(
    lease: str | BudgetReservationLease | None,
    *,
    settled_cost: float,
) -> None:
    """Settle a durable concurrent lease; sequential leases only release."""

    if lease is None:
        return
    if isinstance(lease, BudgetReservationLease):
        settle_tracked_budget_reservation(lease, settled_cost=settled_cost)
        return
    release_budget_scope(lease)


def agent_retry_safe_enabled(explicit: Any | None) -> bool:
    """Whether retries on agent SDK calls are allowed."""
    if explicit is not None:
        return truthy_env(explicit)
    return truthy_env(os.environ.get(AGENT_RETRY_SAFE_ENV))


# ---------------------------------------------------------------------------
# Empty-response classification and schema-error detection
# ---------------------------------------------------------------------------


def _compact_diagnostics(diagnostics: dict[str, Any], *, max_len: int = 600) -> str:
    """Render diagnostics dict into a bounded JSON string for errors/logging."""
    try:
        rendered = _json.dumps(diagnostics, sort_keys=True, ensure_ascii=True, default=str)
    except Exception:
        rendered = str(diagnostics)
    if len(rendered) <= max_len:
        return rendered
    return rendered[:max_len] + "...(truncated)"


def _raise_empty_response(
    *,
    provider: str,
    classification: str,
    retryable: bool,
    diagnostics: dict[str, Any],
) -> NoReturn:
    """Raise typed empty-response error with structured diagnostics."""
    payload = dict(diagnostics)
    payload["provider"] = provider
    payload["classification"] = classification
    payload["retryable"] = retryable
    message = (
        f"Empty content from LLM [{provider}:{classification} retryable={retryable}] "
        f"diagnostics={_compact_diagnostics(payload)}"
    )
    raise LLMEmptyResponseError(
        message,
        retryable=retryable,
        classification=classification,
        diagnostics=payload,
    )


class _NativeSchemaFallback(Exception):
    """Signal native-schema rejection and trigger instructor fallback."""


# Patterns indicating the provider rejected the JSON schema itself (not a
# transient error).  When detected in the native JSON-schema path, the call
# falls back to the instructor path which prompts for JSON instead of
# enforcing via API-level schema constraints.
_SCHEMA_ERROR_PATTERNS: list[str] = [
    "nesting depth",
    "schema is invalid",
    "schema exceeds",
    "invalid schema",
    "unsupported schema",
    "schema too complex",
    "schema validation",
    "not a valid json schema",
    "response_format",
]


def _is_schema_error(error: Exception) -> bool:
    """Check if an error indicates the provider rejected the response schema."""
    error_str = str(error).lower()
    # Must be a 400-class error (BadRequest), not a transient/server error
    error_type = type(error).__name__.lower()
    is_bad_request = "badrequest" in error_type or "invalid_argument" in error_str or "400" in error_str
    if not is_bad_request:
        return False
    return any(p in error_str for p in _SCHEMA_ERROR_PATTERNS)


# ---------------------------------------------------------------------------
# GPT-5 / Responses API sampling and param-policy constants
# ---------------------------------------------------------------------------

_GPT5_ALWAYS_STRIP_SAMPLING = {"gpt-5", "gpt-5-mini", "gpt-5-nano"}
_GPT5_REASONING_GATED_SAMPLING = {
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.6",
    "gpt-5.6-terra",
    "gpt-5.1-chat-latest",
    "gpt-5.2-chat-latest",
}
# Models that support long-thinking (5-10 min) and need background polling
_LONG_THINKING_MODELS = {"gpt-5.2-pro", "gpt-5.5-pro"}
_LONG_THINKING_REASONING_EFFORTS = {"high", "xhigh"}
_GPT5_SAMPLING_PARAMS = ("temperature", "top_p", "logprobs", "top_logprobs")
_OPENROUTER_LUNA_UNSUPPORTED_PARAMS = frozenset({"temperature"})
_UNSUPPORTED_PARAM_POLICY_ENV = "LLM_CLIENT_UNSUPPORTED_PARAM_POLICY"
_UNSUPPORTED_PARAM_POLICIES = frozenset({"coerce_and_warn", "error"})
_UNSUPPORTED_PARAM_POLICY_ALIASES = {
    "warn": "coerce_and_warn",
    "coerce": "coerce_and_warn",
    # Kept as a compatibility spelling. Parameter omission is never silent.
    "silent": "coerce_and_warn",
    "strict": "error",
    "raise": "error",
    "error_only": "error",
}


# ---------------------------------------------------------------------------
# Param coercion and stripping
# ---------------------------------------------------------------------------


def _strip_incompatible_sampling_params(model: str, call_kwargs: dict[str, Any]) -> list[str]:
    """Drop sampling params that are unsupported for GPT-5 family variants.

    GPT-5 legacy models reject sampling controls entirely in many reasoning
    configurations. Keeping this normalization at the client layer avoids
    provider-specific 400s and silent retries when callers pass generic kwargs.
    """
    base = _base_model_name(model)
    reasoning_effort = str(call_kwargs.get("reasoning_effort", "")).strip().lower()

    should_strip = False
    if base in _GPT5_ALWAYS_STRIP_SAMPLING:
        should_strip = True
    elif base in _GPT5_REASONING_GATED_SAMPLING and reasoning_effort and reasoning_effort != "none":
        should_strip = True

    if not should_strip:
        return []

    removed: list[str] = []
    for key in _GPT5_SAMPLING_PARAMS:
        if key in call_kwargs:
            call_kwargs.pop(key, None)
            removed.append(key)
    return removed


def _strip_route_incompatible_params(model: str, call_kwargs: dict[str, Any]) -> tuple[list[str], str | None]:
    """Remove parameters rejected by a known provider/model route.

    Keep this evidence-specific: Luna's OpenRouter native-schema route is
    known to reject an explicit temperature, but that does not establish that
    other sampling controls are unsupported.
    """
    if model.strip().lower() != "openrouter/openai/gpt-5.6-luna":
        return [], None

    removed = sorted(
        key for key in _OPENROUTER_LUNA_UNSUPPORTED_PARAMS if key in call_kwargs
    )
    for key in removed:
        call_kwargs.pop(key, None)
    return removed, "openrouter_luna_native_schema_compatibility"


def _resolve_unsupported_param_policy(explicit_policy: Any) -> str:
    """Resolve the unsupported-param policy from explicit arg or env."""
    raw = explicit_policy
    if raw is None:
        raw = os.environ.get(_UNSUPPORTED_PARAM_POLICY_ENV, "coerce_and_warn")
    policy = str(raw).strip().lower()
    policy = _UNSUPPORTED_PARAM_POLICY_ALIASES.get(policy, policy)
    if policy not in _UNSUPPORTED_PARAM_POLICIES:
        allowed = ", ".join(sorted(_UNSUPPORTED_PARAM_POLICIES))
        raise ValueError(
            f"Invalid unsupported_param_policy={raw!r}. "
            f"Allowed: {allowed} (or aliases: {', '.join(sorted(_UNSUPPORTED_PARAM_POLICY_ALIASES))})"
        )
    return policy


def _coerce_model_incompatible_params(
    *,
    model: str,
    kwargs: dict[str, Any],
    policy: str,
    warning_sink: list[str] | None = None,
) -> list[str]:
    """Normalize unsupported params and emit loud diagnostics."""
    removed: list[str] = []

    # Bare GPT-5 models route via responses API and reject temperature.
    if _is_responses_api_model(model) and "temperature" in kwargs:
        kwargs.pop("temperature", None)
        removed.append("temperature")

    # GPT-5 family sampling incompatibilities across providers/completions.
    removed.extend(_strip_incompatible_sampling_params(model, kwargs))
    route_removed, route_rule = _strip_route_incompatible_params(model, kwargs)
    removed.extend(route_removed)

    if not removed:
        return []

    removed_unique = sorted(set(removed))
    rule = route_rule or "gpt5_sampling_compatibility"
    detail = (
        f"COERCE_PARAMS model={model} policy={policy} "
        f"removed={','.join(removed_unique)} "
        f"rule={rule}"
    )
    if policy == "error":
        raise LLMCapabilityError(
            f"Unsupported params for model {model}: {', '.join(removed_unique)}. "
            "Use unsupported_param_policy='coerce_and_warn' to auto-coerce."
        )
    # A caller-supplied parameter that does not reach the provider is always
    # observable. The legacy "silent" spelling resolves to coerce_and_warn.
    logger.warning(detail)
    if warning_sink is not None:
        warning_sink.append(detail)
    return removed_unique


def _strip_llm_internal_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop llm_client-internal keys from a kwargs mapping.

    Internal keys are conventionally prefixed with ``_`` and used for private
    control flow (for example ``_lifecycle_monitor``). They are not part of the
    provider contract and are intentionally excluded from cache keying and
    provider payloads.
    """
    internal = {
        "budget_scope_trace_id",
        "budget_scope_mode",
        "budget_reservation",
    }
    return {k: v for k, v in kwargs.items() if not k.startswith("_") and k not in internal}


def _apply_max_tokens(model: str, call_kwargs: dict[str, Any]) -> None:
    """Clamp explicit output-token caps to the model maximum when present.

    The client does not invent output-token ceilings when callers omit them.
    Defaulting to the provider maximum turns routine calls into accidental
    high-cost requests, especially for structured-output workloads where a
    large generated cap is not the same as a useful response. When callers do
    supply an explicit cap, this helper only prevents provider-side
    ``max_tokens > model_max`` validation errors.

    Silently skips if model info lookup fails (unknown/custom models).
    """
    try:
        info = litellm.get_model_info(model)
    except Exception:
        return  # Unknown model — pass through unchanged

    model_max = info.get("max_output_tokens")
    if not model_max:
        return

    # Determine which key the caller used (if any)
    token_key = None
    for key in ("max_completion_tokens", "max_tokens"):
        if key in call_kwargs:
            token_key = key
            break

    if token_key:
        # Clamp to model's max
        if call_kwargs[token_key] > model_max:
            logger.debug(
                "Clamping %s from %d to %d for %s",
                token_key, call_kwargs[token_key], model_max, model,
            )
            call_kwargs[token_key] = model_max
    else:
        return


# ---------------------------------------------------------------------------
# Agent model detection and execution-mode contracts
# ---------------------------------------------------------------------------

_CODEX_AGENT_ALIASES: frozenset[str] = frozenset({"codex-mini-latest"})

# Matches bare model names that belong to the Codex family but don't start
# with the "codex/" prefix — e.g. "gpt-5.3-codex", "gpt-5.1-codex-mini".
# The pattern looks for "-codex" at a word boundary (end of string or
# followed by a hyphen).
_CODEX_FAMILY_RE = re.compile(r"-codex(?:-|$)", re.IGNORECASE)


def _codex_detection_base(model: str) -> str:
    """Return the provider-agnostic lowercase model name for Codex detection."""

    return str(model or "").rsplit("/", 1)[-1].lower()


def _is_codex_alias_model(model: str) -> bool:
    """Check if a model is a named Codex SDK alias, even with provider prefixes."""

    return _codex_detection_base(model) in _CODEX_AGENT_ALIASES


def _is_codex_family_model(model: str) -> bool:
    """Check if a model name belongs to the Codex family by naming pattern.

    Recognizes models like ``gpt-5.3-codex``, ``gpt-5.1-codex-mini``, and
    ``gpt-5.1-codex-max`` that use the Codex SDK but don't follow the
    ``codex/`` prefix convention.  Provider prefixes (``openai/``,
    ``openrouter/openai/``) are stripped before matching.
    """
    # Strip provider prefix to get the bare model name.
    base = _codex_detection_base(model)
    return bool(_CODEX_FAMILY_RE.search(base))


def _is_agent_model(model: str) -> bool:
    """Check if model routes to an agent SDK instead of litellm.

    Agent models like "claude-code" or "claude-code/sonnet" use the Claude
    Agent SDK. "openai-agents/*" is reserved for future OpenAI Agents SDK.
    Codex-family models (e.g. "gpt-5.3-codex") are also recognized.
    """
    lower = model.lower()
    for prefix in ("claude-code", "codex", "openai-agents"):
        if lower == prefix or lower.startswith(prefix + "/"):
            return True
    # Support selected Codex aliases that map to Codex agent SDK models.
    if _is_codex_alias_model(model):
        return True
    # Recognize Codex-family models by naming pattern (e.g. gpt-5.3-codex).
    if _is_codex_family_model(model):
        return True
    return False


ExecutionMode = Literal["text", "structured", "workspace_agent", "workspace_tools"]
_VALID_EXECUTION_MODES: frozenset[str] = frozenset(
    {"text", "structured", "workspace_agent", "workspace_tools"}
)
_AGENT_ONLY_KWARGS: frozenset[str] = frozenset(
    {
        "allowed_tools",
        "agent_idle_timeout",
        "cwd",
        "max_turns",
        "max_tool_calls",
        "permission_mode",
        "max_budget_usd",
        "sandbox_mode",
        "working_directory",
        "approval_policy",
        "model_reasoning_effort",
        "network_access_enabled",
        "web_search_enabled",
        "additional_directories",
        "skip_git_repo_check",
        "yolo_mode",
        "codex_home",
    }
)


def _validate_execution_contract(
    *,
    models: list[str],
    execution_mode: str,
    kwargs: dict[str, Any],
    caller: str,
) -> None:
    """Validate model/kwargs capability compatibility before dispatch."""
    if execution_mode not in _VALID_EXECUTION_MODES:
        valid = ", ".join(sorted(_VALID_EXECUTION_MODES))
        raise ValueError(f"Invalid execution_mode={execution_mode!r}. Valid values: {valid}")

    if execution_mode == "workspace_agent":
        non_agent = [m for m in models if not _is_agent_model(m)]
        if non_agent:
            raise LLMCapabilityError(
                f"{caller}: execution_mode='workspace_agent' requires agent models "
                f"(codex/claude-code/openai-agents). Incompatible models: {non_agent}"
            )

    if execution_mode == "workspace_tools":
        agent_models = [m for m in models if _is_agent_model(m)]
        if agent_models:
            raise LLMCapabilityError(
                f"{caller}: execution_mode='workspace_tools' requires non-agent models. "
                f"Incompatible models: {agent_models}"
            )
        if not any(k in kwargs for k in ("python_tools", "mcp_servers", "mcp_sessions")):
            raise LLMCapabilityError(
                f"{caller}: execution_mode='workspace_tools' requires python_tools "
                "or mcp_servers/mcp_sessions."
            )

    # max_turns/max_tool_calls are valid for non-agent models when using MCP/python_tools
    has_tool_loop = any(k in kwargs for k in ("mcp_servers", "mcp_sessions", "python_tools"))
    check_set = _AGENT_ONLY_KWARGS - {"max_turns", "max_tool_calls"} if has_tool_loop else _AGENT_ONLY_KWARGS
    agent_only = sorted(k for k in kwargs if k in check_set)
    if agent_only:
        non_agent = [m for m in models if not _is_agent_model(m)]
        agent_models = [m for m in models if _is_agent_model(m)]
        if non_agent and not agent_models:
            raise LLMCapabilityError(
                f"{caller}: agent-only kwargs {agent_only} are incompatible with "
                f"non-agent model(s) {non_agent}. Use codex/claude-code or remove "
                "agent-only kwargs."
            )
        if non_agent and agent_models:
            logger.warning(
                "%s: mixed agent/non-agent fallback chain detected; agent-only kwargs %s "
                "will be ignored on non-agent fallback legs.",
                caller,
                agent_only,
            )


def _coerce_model_kwargs_for_execution(
    *,
    current_model: str,
    kwargs: dict[str, Any],
    warning_sink: list[str] | None,
) -> dict[str, Any]:
    """Strip kwargs unsupported for the current execution leg.

    This enables mixed agent/non-agent fallback chains by removing agent-only
    kwargs when executing non-agent models.
    """
    # Drop llm_client internal runtime kwargs from all execution paths.
    # They are injected for orchestration/observability and should never be
    # hashed into cache keys or sent into provider/SDK payloads.
    internal_removed = sorted(k for k in kwargs if k.startswith("_"))

    if _is_agent_model(current_model):
        return {k: v for k, v in kwargs.items() if k not in internal_removed}

    # max_turns/max_tool_calls are valid for non-agent models when using
    # MCP/python_tools (they control the tool-call loop, not the agent SDK).
    # This mirrors the exemption in _validate_execution_contract.
    has_tool_loop = any(k in kwargs for k in ("mcp_servers", "mcp_sessions", "python_tools"))
    strip_set = _AGENT_ONLY_KWARGS - {"max_turns", "max_tool_calls"} if has_tool_loop else _AGENT_ONLY_KWARGS
    removed = sorted(k for k in kwargs if k in strip_set)
    all_removed = sorted(set([*internal_removed, *removed]))
    if not all_removed:
        return kwargs

    model_kwargs = dict(kwargs)
    for key in all_removed:
        model_kwargs.pop(key, None)

    if not removed:
        return model_kwargs

    detail = (
        f"COERCE_PARAMS model={current_model} policy=coerce_and_warn "
        f"removed={','.join(removed)} "
        "rule=agent_fallback_compatibility"
    )
    logger.warning(detail)
    if warning_sink is not None:
        warning_sink.append(detail)
    return model_kwargs


# ---------------------------------------------------------------------------
# Model deprecation warnings
# ---------------------------------------------------------------------------

# Models that are HARD-BLOCKED: always raise DeprecatedModelError regardless
# of env vars.  Add a model here when a strictly better alternative exists at
# equal-or-lower cost and there is no legitimate reason for a new call to use
# it (e.g., it was retired by the provider, or it is strictly dominated).
# Key: model substring (matched case-insensitively).
# Value: (replacement, reason).
_HARD_BLOCKED_MODELS: dict[str, tuple[str, str]] = {
    "gpt-5.4": (
        "gpt-5.6-luna (preferred) OR an explicit non-GPT-5.4 route when Luna "
        "cannot satisfy the required execution contract",
        "GPT-5.4-family models are banned by ecosystem policy in every execution "
        "lane, including raw provider routes, Mini/Nano variants, and Codex aliases.",
    ),
    "gpt-5.5": (
        "gpt-5.6 (Sol) OR gpt-5.6-terra",
        "GPT-5.5 is retired from ecosystem routing. Use GPT-5.6 Sol for "
        "maximum-quality work or GPT-5.6 Terra for an explicit lower-cost route.",
    ),
    "openrouter/auto": (
        "an explicit, policy-approved model ID",
        "OpenRouter Auto Router selects the final model account-side, so "
        "llm_client cannot prove before dispatch that a banned model is excluded.",
    ),
    "@preset/": (
        "an explicit, policy-approved model ID and provider routing kwargs",
        "OpenRouter presets can replace the requested model or add fallbacks "
        "account-side, so llm_client cannot enforce its model ban before dispatch.",
    ),
    "opus": (
        "claude-code/sonnet for Claude workspace-agent review OR "
        "the appropriate non-banned llm_client model tier for ordinary calls",
        "Opus-family models are banned by ecosystem policy in every execution "
        "lane, including raw provider routes and claude-code aliases.",
    ),
    "fable": (
        "openrouter/openai/gpt-5.6-sol OR openrouter/x-ai/grok-4.5 OR "
        "openrouter/z-ai/glm-5.2",
        "Fable-family models are banned by ecosystem policy. Do not use them for "
        "new calls, even with ordinary model_override_acceptance metadata.",
    ),
    "gpt-5.1-mini": (
        "openrouter/deepseek/deepseek-v4-flash",
        "GPT-5.1 Mini is prohibited by the shared model-execution policy.",
    ),
    "gpt-5-mini": (
        "openrouter/deepseek/deepseek-v4-flash",
        "GPT-5 Mini is prohibited by the shared model-execution policy.",
    ),
    "codex-mini": (
        "codex/gpt-5.6-luna",
        "Codex Mini routes are prohibited by the shared model-execution policy.",
    ),
    "gpt-4o-mini": (
        "deepseek/deepseek-chat OR gemini/gemini-2.5-flash",
        "GPT-4o-mini (intel 30, $0.15/$0.60) is outclassed by DeepSeek V3.2 "
        "(intel 42, $0.28/$0.42) and MiMo-V2-Flash (intel 41, $0.15 blended). "
        "Both are smarter AND cheaper. This model is hard-blocked.",
    ),
    "o4-mini": (
        "o3-mini",
        "o4-mini was retired by OpenAI on Feb 16, 2026 and no longer accepts "
        "requests. Use o3-mini for reasoning tasks or DeepSeek V4 Flash for general tasks.",
    ),
    "mistral-large": (
        "deepseek/deepseek-chat OR gemini/gemini-2.5-flash",
        "Mistral Large (intel ~27, $2.75 blended) is dramatically overpriced "
        "for its quality. DeepSeek V3.2 (intel 42, $0.32) is 8x cheaper and smarter. "
        "This model is hard-blocked.",
    ),
}

# Models that are soft-deprecated: warn loudly by default; raise
# LLMModelNotFoundError if LLM_CLIENT_STRICT_MODELS=1.  Use for models that
# are outclassed but may still have legitimate uses (benchmarking baselines,
# explicit user opt-in, etc.).
# Key: model substring (matched case-insensitively).
# Value: (replacement suggestion, reason).
_DEPRECATED_MODELS: dict[str, tuple[str, str]] = {
    # gpt-4o moved to _WARNED_MODELS (warn-only, never banned)
    "o1-mini": (
        "o3-mini",
        "o1-mini is deprecated. Use o3-mini for reasoning tasks.",
    ),
    "o1-pro": (
        "o3",
        "o1-pro ($150/$600) is superseded by o3 ($2/$8) which is better at "
        "reasoning at a fraction of the cost.",
    ),
    "gemini-1.5": (
        "gemini/gemini-2.5-flash OR gemini/gemini-2.5-pro",
        "All Gemini 1.5 models are superseded by 2.5+ equivalents at the "
        "same price with better quality. Use gemini-2.5-flash or gemini-2.5-pro.",
    ),
    "gemini-2.0-flash": (
        "gemini/gemini-2.5-flash",
        "Gemini 2.0 Flash is superseded by 2.5 Flash at the same price with "
        "significantly better quality.",
    ),
    "claude-3-5": (
        "anthropic/claude-sonnet-4-5-20250929 OR anthropic/claude-haiku-4-5-20251001",
        "Claude 3.5 models are superseded by 4.5 equivalents at the same price "
        "with better quality.",
    ),
    "claude-3-sonnet": (
        "anthropic/claude-sonnet-4-5-20250929",
        "Claude 3 Sonnet is superseded by Sonnet 4.5 at the same price with "
        "much better quality.",
    ),
    "claude-3-haiku": (
        "anthropic/claude-haiku-4-5-20251001",
        "Claude 3 Haiku is superseded by Haiku 4.5 at the same price with "
        "much better quality.",
    ),
}

# Models that are outclassed but still usable — warn loudly, never ban.
# Same format as _DEPRECATED_MODELS. Useful for benchmarking against baselines.
_WARNED_MODELS: dict[str, tuple[str, str]] = {
    "gpt-4o": (
        "gpt-5",
        "GPT-4o ($2.50/$10) is outclassed by GPT-5 ($1.25/$10) — "
        "GPT-5 is cheaper and smarter. Consider switching.",
    ),
}

# Models that match a deprecated pattern but should NOT be flagged
_DEPRECATED_MODEL_EXCEPTIONS: set[str] = {
    "gpt-4o-mini",  # has its own entry — prevent double-match from gpt-4o
    "gemini-2.0-flash-lite",  # NOT deprecated — cheapest Google model, no 2.5 equivalent
}


def _check_model_deprecation(model: str) -> None:
    """Raise or warn if the model is hard-blocked or soft-deprecated.

    **Hard-blocked models** (``_HARD_BLOCKED_MODELS``): always raise
    ``DeprecatedModelError`` regardless of env vars.  These are models where
    a strictly better alternative exists and there is no legitimate reason for
    a new call to reach them.

    **Soft-deprecated models** (``_DEPRECATED_MODELS``): emit a loud warning
    by default.  Set ``LLM_CLIENT_STRICT_MODELS=1`` to raise
    ``LLMModelNotFoundError`` instead (recommended for CI and benchmarks).

    **Outclassed-but-usable models** (``_WARNED_MODELS``): always warn, never
    raise — useful for benchmarking against older baselines.
    """
    import warnings as _warnings

    lower = model.lower()

    # 1. Hard-blocked: raise unconditionally.
    for pattern, (replacement, reason) in _HARD_BLOCKED_MODELS.items():
        if pattern in lower:
            if any(exc in lower and exc != pattern for exc in _DEPRECATED_MODEL_EXCEPTIONS):
                continue
            raise DeprecatedModelError(
                f"HARD-BLOCKED MODEL: {model}\n"
                f"Reason: {reason}\n"
                f"Use instead: {replacement}",
                replacement=replacement,
            )

    # 2. Soft-deprecated: warn by default; raise if STRICT_MODELS=1.
    strict = os.environ.get("LLM_CLIENT_STRICT_MODELS", "").strip() == "1"
    for pattern, (replacement, reason) in _DEPRECATED_MODELS.items():
        if pattern in lower:
            if any(exc in lower and exc != pattern for exc in _DEPRECATED_MODEL_EXCEPTIONS):
                continue
            if strict:
                raise LLMModelNotFoundError(
                    f"BANNED MODEL: {model}. {reason} Use instead: {replacement}. "
                    f"(LLM_CLIENT_STRICT_MODELS=1 is set — deprecated models are blocked.)"
                )
            warning_msg = (
                f"\n{'=' * 72}\n"
                f"WARNING: DEPRECATED MODEL DETECTED: {model}\n"
                f"{'=' * 72}\n"
                f"\n"
                f"STOP. DO NOT USE THIS MODEL UNLESS THE USER HAS SPECIFICALLY "
                f"TOLD YOU TO AND HAS CONFIRMED THEY UNDERSTAND WHY NOT TO USE IT. "
                f"YOU MUST GET USER PERMISSION. STOP NOW AND ASK IF YOU DON'T HAVE IT.\n"
                f"\n"
                f"Reason: {reason}\n"
                f"\n"
                f"Use instead: {replacement}\n"
                f"{'=' * 72}\n"
            )
            logger.warning(warning_msg)
            _warnings.warn(warning_msg, DeprecationWarning, stacklevel=3)
            return

    # 3. Outclassed-but-usable: loud warning, never banned.
    for pattern, (replacement, reason) in _WARNED_MODELS.items():
        if pattern in lower:
            if any(exc in lower and exc != pattern for exc in _DEPRECATED_MODEL_EXCEPTIONS):
                continue
            warning_msg = (
                f"\n{'=' * 72}\n"
                f"WARNING: OUTCLASSED MODEL: {model}\n"
                f"{'=' * 72}\n"
                f"Reason: {reason}\n"
                f"Use instead: {replacement}\n"
                f"{'=' * 72}\n"
            )
            logger.warning(warning_msg)
            _warnings.warn(warning_msg, UserWarning, stacklevel=3)
            return


PROMPT_SIZE_STRICT_ENV = "LLM_CLIENT_PROMPT_SIZE_STRICT"

_CHARS_PER_TOKEN_ESTIMATE = 4
"""Shared heuristic with ``llm_client.agent.context_budget``.

Exact tokenization is model-specific and would require a per-provider
tokenizer. This contract exists to catch payloads that are multiples of their
declared ceiling, where a 4-chars-per-token estimate is amply precise.

Measured against one real stored payload (process_tracing.central_claim_review,
615,835 provider-reported prompt tokens) this estimate returned 788,548 -- it
over-counted by ~28% on JSON-heavy content. Treat the number as an order-of-
magnitude signal for contract breaches, never as a billing or context-window
figure; ``prompt_tokens`` on the observability row is the authority for those.
"""

_TASK_PROMPT_BUDGETS: dict[str, int] = {}
_TASK_PROMPT_BUDGETS_LOCK = threading.Lock()


def register_task_prompt_budget(task: str, max_prompt_tokens: int) -> None:
    """Declare the prompt-size ceiling for one task.

    Consumers register their own ceilings at import time; ``llm_client`` owns
    the mechanism and never hard-codes any consumer's task names. This keeps
    the shared substrate free of project-specific policy while still applying
    one enforcement path to every project.

    Registration is idempotent for an identical value and fails loud on a
    conflicting re-registration, so two modules cannot silently disagree about
    the same task's ceiling.
    """

    normalized = str(task).strip()
    if not normalized:
        raise ValueError("task must be a non-empty string")
    if not isinstance(max_prompt_tokens, int) or isinstance(max_prompt_tokens, bool):
        raise TypeError(f"max_prompt_tokens must be an int, got {max_prompt_tokens!r}")
    if max_prompt_tokens <= 0:
        raise ValueError("max_prompt_tokens must be positive")

    with _TASK_PROMPT_BUDGETS_LOCK:
        existing = _TASK_PROMPT_BUDGETS.get(normalized)
        if existing is not None and existing != max_prompt_tokens:
            raise ValueError(
                f"conflicting prompt budget for task {normalized!r}: "
                f"{existing} already registered, refusing to overwrite with "
                f"{max_prompt_tokens}"
            )
        _TASK_PROMPT_BUDGETS[normalized] = max_prompt_tokens


def get_task_prompt_budget(task: str | None) -> int | None:
    """Return the registered prompt ceiling for a task, if any."""

    if not task:
        return None
    with _TASK_PROMPT_BUDGETS_LOCK:
        return _TASK_PROMPT_BUDGETS.get(str(task).strip())


def prompt_size_strict_mode() -> bool:
    """Whether an over-budget prompt raises instead of warning.

    Warn-by-default is deliberate. These calls are frequently made inside
    long-running repair and review loops; hard-failing one by default would
    convert a cost problem into an availability problem. CI and benchmark runs
    opt into strict mode, matching ``tags_strict_mode``.
    """

    if truthy_env(os.environ.get(PROMPT_SIZE_STRICT_ENV)):
        return True
    return truthy_env(os.environ.get("CI"))


def estimate_prompt_tokens(serialized_prompt: str) -> int:
    """Estimate prompt tokens from an already-serialized payload."""

    return len(serialized_prompt) // _CHARS_PER_TOKEN_ESTIMATE


def check_prompt_size(
    task: str,
    serialized_prompt: str,
    *,
    max_prompt_tokens: int | None = None,
    warning_sink: list[str] | None = None,
) -> int:
    """Measure a serialized prompt against its declared ceiling.

    Resolution order for the ceiling: the explicit ``max_prompt_tokens``
    argument, then the value registered for ``task``, then no ceiling. With no
    ceiling the payload is still measured and returned so callers and
    observability can record it -- measurement is unconditional, enforcement is
    opt-in.

    The payload is never truncated to fit. Silently trimming a caller's prompt
    would change the model's inputs behind its back; this substrate reports the
    breach and lets the caller decide.

    Returns:
        The estimated prompt tokens for ``serialized_prompt``.

    Raises:
        LLMPromptBudgetExceededError: When over budget and strict mode is on.
    """

    estimated = estimate_prompt_tokens(serialized_prompt)
    ceiling = max_prompt_tokens if max_prompt_tokens is not None else get_task_prompt_budget(task)
    if ceiling is None or estimated <= ceiling:
        return estimated

    overage = estimated / ceiling
    message = (
        f"Prompt size contract exceeded for task {task!r}: "
        f"~{estimated:,} estimated prompt tokens > {ceiling:,} declared ceiling "
        f"({overage:.1f}x). The payload was not truncated."
    )
    if prompt_size_strict_mode():
        raise LLMPromptBudgetExceededError(message)
    logger.warning(message)
    if warning_sink is not None:
        warning_sink.append(f"PROMPT_SIZE: {estimated} > {ceiling} ({overage:.1f}x)")
    return estimated
