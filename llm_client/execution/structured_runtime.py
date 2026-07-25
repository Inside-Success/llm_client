"""Internal runtimes for structured-output entrypoints.

This module owns the implementation behind the public
``call_llm_structured`` and ``acall_llm_structured`` facades. The public API
remains in ``client.py``; this module holds the structured-call control flow so
runtime logic can be grouped by workload family without changing
caller-facing signatures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from importlib import import_module
import queue
import threading
from typing import Any, Awaitable, Callable, Literal, NoReturn, TypeVar, cast
from uuid import uuid4

from llm_client.core.client import (
    AsyncCachePolicy,
    CachePolicy,
    Hooks,
    LLMCallResult,
    RetryPolicy,
)
from llm_client.core.config import ClientConfig
from llm_client.core.errors import (
    LLMCapabilityError,
    LLMConfigurationError,
    LLMLogicalDeadlineError,
    _unwrap_instructor_retry,
)
from llm_client.execution.call_contracts import StructuredOutputPolicy
from llm_client.langfuse_callbacks import inject_metadata as _inject_langfuse_metadata
from pydantic import BaseModel, ValidationError

import hashlib as _hashlib
import json as _json
import logging as _logging
import math as _math
import os as _os
import re as _re
import threading as _threading
import time as _time

import litellm
import llm_client.io_log as _io_log

from llm_client.core.models import supports_structured_output as _registry_supports_structured_output
from llm_client.execution.timeout_policy import _await_with_safety_ceiling
from llm_client.parsing_utils import safe_json_loads as _safe_json_loads
from llm_client.observability.raw_artifacts import (
    StructuredRawArtifactError,
    prepare_structured_raw_artifact_store,
    write_structured_raw_artifact,
)
from llm_client.observability.structured_attempts import (
    AttemptEventType,
    AttemptFailureClass,
    RecoveryDecision,
    StructuredAttemptEvent,
    StructuredValidationIssue,
    record_structured_attempt_event,
)
from llm_client.observability.attempt_diagnostics import (
    AttemptDiagnosticEnvelope,
    TimeoutKind,
    exception_fingerprint,
    record_attempt_diagnostic,
)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class _EmptyStructuredContentError(ValueError):
    """A response object arrived but contained no structured content."""

_client: Any = import_module("llm_client.core.client")
_structured_logger = _logging.getLogger("llm_client.structured_runtime")
_INSTRUCTOR_INIT_LOCK = _threading.Lock()
_ROUTE_CERTIFICATION_OBSERVATION_ENV = (
    "LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION"
)
_PROVIDER_SCHEMA_NAME_MAX_LENGTH = 64


def _provider_schema_name(response_model: type[BaseModel]) -> str:
    """Return a stable provider-safe identifier for a structured response schema."""

    raw_name = response_model.__name__
    safe_name = "".join(
        character if character.isalnum() or character in "_-" else "_"
        for character in raw_name
    )
    if safe_name == raw_name and len(safe_name) <= _PROVIDER_SCHEMA_NAME_MAX_LENGTH:
        return safe_name
    digest = _hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:12]
    prefix = safe_name[:51].rstrip("_-") or "response_schema"
    return f"{prefix}_{digest}"


def _instructor_from_litellm(create_fn: Any) -> Any:
    """Construct an Instructor client without racing global registration.

    Instructor client construction may lazily mutate process-global provider
    registration. Serializing the public construction seam supports both the
    declared 1.x dependency and newer implementations without importing
    version-private registry modules.
    """

    import instructor

    with _INSTRUCTOR_INIT_LOCK:
        return instructor.from_litellm(create_fn)


def _model_supports_native_schema(model: str) -> bool:
    """Native json_schema capability: llm_client registry first, litellm fallback.

    The curated model registry is authoritative for models it knows — litellm's
    capability map lags new OpenRouter releases and was silently rerouting
    schema-capable models (deepseek-v4-flash, minimax-m3) onto the instructor
    fallback. Unknown models still defer to litellm.
    """
    import litellm

    registry_capability = _registry_supports_structured_output(model)
    if registry_capability is not None:
        return bool(registry_capability)
    return bool(litellm.supports_response_schema(model=model))


def _record_openrouter_native_route_observation(
    *,
    result: LLMCallResult,
    provider_schema: dict[str, Any],
    response_model: type[BaseModel],
) -> None:
    """Record exact OpenRouter route evidence without changing model execution.

    Metadata enrichment occurs only after a successful native-schema response.
    It cannot cause a model retry or fallback.  A failed enrichment remains
    visible on the returned result rather than pretending that the route was
    certified.
    """

    resolved_model = result.resolved_model or result.model
    if not resolved_model.startswith("openrouter/") or result.cache_hit:
        return
    observation_policy = _os.environ.get(
        _ROUTE_CERTIFICATION_OBSERVATION_ENV,
        "disabled",
    ).strip().lower()
    if observation_policy in {"0", "false", "off", "disabled"}:
        _structured_logger.info(
            "ROUTE_CERTIFICATION_OBSERVATION_DISABLED model=%s policy_env=%s",
            resolved_model,
            _ROUTE_CERTIFICATION_OBSERVATION_ENV,
        )
        return
    if observation_policy not in {"1", "true", "on", "enabled"}:
        raise ValueError(
            f"{_ROUTE_CERTIFICATION_OBSERVATION_ENV} must be enabled or disabled"
        )
    try:
        from llm_client.route_certification_runtime import (
            observe_openrouter_native_success_from_runtime,
        )

        observation = observe_openrouter_native_success_from_runtime(
            result=result,
            provider_schema=provider_schema,
            schema_class=response_model.__name__,
        )
    except Exception as error:
        message = (
            "ROUTE_CERTIFICATION_OBSERVATION_FAILED "
            f"model={resolved_model} error_type={type(error).__name__} error={error}"
        )
        _structured_logger.warning(message)
        result.warnings.append(message)
        result.warning_records.append(
            {
                "code": "ROUTE_CERTIFICATION_OBSERVATION_FAILED",
                "category": "route_certification",
                "message": message,
                "remediation": (
                    "Inspect the retained structured call and OpenRouter generation metadata; "
                    "do not infer provider endpoint identity from the requested model."
                ),
            }
        )
    else:
        result.warning_records.append(
            {
                "code": "ROUTE_CERTIFICATION_OBSERVED",
                "category": "route_certification",
                "message": f"Recorded {observation.observation_id}.",
                "remediation": "Use the route-certification query before treating this route as certified.",
            }
        )


def _deadline_message(timeout: float) -> str:
    """Return the stable error emitted by client-enforced attempt deadlines."""

    return f"structured provider attempt exceeded {timeout:g}s client deadline"


def _normalize_logical_timeout(value: float | None) -> float | None:
    """Validate the optional caller-visible total structured-call budget."""

    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not _math.isfinite(value)
        or value <= 0
    ):
        raise LLMConfigurationError(
            "logical_timeout must be a finite number greater than zero",
            error_code="invalid_logical_timeout",
        )
    return float(value)


def _logical_deadline_at(logical_timeout: float | None) -> float | None:
    normalized = _normalize_logical_timeout(logical_timeout)
    return None if normalized is None else _time.monotonic() + normalized


def _effective_attempt_timeout(
    timeout: float,
    *,
    deadline_at: float | None,
) -> tuple[float, bool]:
    """Cap one provider attempt by the remaining logical-call budget."""

    if deadline_at is None:
        return timeout, False
    remaining = deadline_at - _time.monotonic()
    if remaining <= 0:
        raise LLMLogicalDeadlineError("structured logical call deadline elapsed")
    if timeout <= 0 or remaining < timeout:
        return remaining, True
    return timeout, False


def _run_sync_with_deadline(
    invoke: Callable[[], R],
    *,
    timeout: float,
    logical_cap: bool = False,
) -> R:
    """Run one sync provider attempt behind a caller-visible hard deadline.

    Python cannot terminate a thread blocked in a third-party HTTP stack. A
    timed-out attempt therefore finishes in a daemon thread while the caller
    receives ``TimeoutError`` and continues through retry/fallback policy.
    """

    if timeout <= 0:
        return invoke()

    outcomes: queue.Queue[tuple[bool, R | BaseException]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            outcomes.put((True, invoke()))
        except BaseException as error:
            outcomes.put((False, error))

    thread = threading.Thread(
        target=run,
        name="llm-client-structured-attempt",
        daemon=True,
    )
    thread.start()
    try:
        succeeded, outcome = outcomes.get(timeout=timeout)
    except queue.Empty as error:
        if logical_cap:
            raise LLMLogicalDeadlineError(
                "structured logical call deadline elapsed",
                original=error,
            ) from error
        raise TimeoutError(_deadline_message(timeout)) from error
    if succeeded:
        return cast(R, outcome)
    raise cast(BaseException, outcome)


async def _run_async_with_deadline(
    invoke: Callable[[], Awaitable[R]],
    *,
    timeout: float,
    logical_cap: bool = False,
) -> R:
    """Await one async provider attempt behind a cancellation deadline."""

    if timeout <= 0:
        return await invoke()
    try:
        return await asyncio.wait_for(invoke(), timeout=timeout)
    except TimeoutError as error:
        if logical_cap:
            raise LLMLogicalDeadlineError(
                "structured logical call deadline elapsed",
                original=error,
            ) from error
        raise TimeoutError(_deadline_message(timeout)) from error


def _robust_validate_json(response_model: type[T], raw_content: str) -> T:
    """Parse and validate JSON from LLM output with best-effort extraction.

    Tries ``model_validate_json`` first (fast path).  If that fails due to
    JSON decoding issues (control characters, fenced markdown, etc.), falls
    back to ``safe_json_loads`` + ``model_validate`` which strips control
    chars, extracts JSON from fences/prose, and uses ``strict=False``.

    Pydantic ``ValidationError`` (schema mismatch) is never swallowed -- only
    JSON-level failures trigger the fallback.
    """
    try:
        return response_model.model_validate_json(raw_content)
    except ValidationError as error:
        # Pydantic reports both JSON decoding and schema mismatches through
        # ValidationError. Normalize transport framing only for the former;
        # field/type/enum violations must remain terminal validation failures.
        if not error.errors() or any(
            issue.get("type") != "json_invalid" for issue in error.errors()
        ):
            raise
    except Exception:
        pass
    _structured_logger.debug(
        "model_validate_json failed on raw content (%d chars), "
        "falling back to safe_json_loads",
        len(raw_content),
    )
    parsed_data = _safe_json_loads(raw_content)
    return response_model.model_validate(parsed_data)


class _StructuredValidationRetry(Exception):
    """Retryable validation error from model_validate_json.

    Raised when the LLM provider returns syntactically valid JSON that passes
    the provider's schema check but fails Pydantic validation (e.g., the
    provider didn't enforce ``minProperties``).  Carries the raw content and
    formatted error so a repair message can be appended on retry.
    """

    def __init__(self, raw_content: str, validation_error: ValidationError) -> None:
        self.raw_content = raw_content
        self.validation_error = validation_error
        super().__init__(
            f"Pydantic validation failed on provider-accepted response: "
            f"{validation_error.error_count()} error(s). "
            f"First: {validation_error.errors()[0]['msg'] if validation_error.errors() else 'unknown'}"
        )


class _StructuredParseRetry(Exception):
    """Retryable malformed JSON received from a structured provider route."""


class _StructuredFinalizationFailure(Exception):
    """Carry a local post-validation failure across retry/fallback kernels.

    Repeating generation cannot repair a hook, cache, cost-normalization, or
    observability failure after the provider response already passed schema
    validation. The marker is private and unwrapped at the public boundary.
    """

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(str(cause) or type(cause).__name__)


class _AttemptCostLedger:
    """Aggregate priceable responses without inventing pre-response charges."""

    def __init__(self) -> None:
        self._started: set[int] = set()
        self._observed: dict[int, tuple[float, str]] = {}

    def mark_started(self, attempt_ordinal: int) -> None:
        """Record that one provider attempt crossed the dispatch boundary."""

        self._started.add(attempt_ordinal)

    def record_response(
        self,
        attempt_ordinal: int,
        *,
        cost: float,
        cost_source: str,
    ) -> None:
        """Bind one returned provider response to its observed price."""

        if attempt_ordinal not in self._started:
            raise RuntimeError("cannot price a structured attempt before it starts")
        if attempt_ordinal in self._observed:
            raise RuntimeError("structured attempt cost recorded more than once")
        self._observed[attempt_ordinal] = (float(cost), cost_source)

    def apply(self, result: LLMCallResult) -> None:
        """Apply logical-call cost and exact coverage to a terminal result."""

        observed = list(self._observed.values())
        if observed:
            total = sum(cost for cost, _source in observed)
            result.cost = total
            result.marginal_cost = total
            if len(observed) > 1:
                result.cost_source = "attempt_aggregate"
            else:
                result.cost_source = observed[0][1]
        result.cost_covers_all_attempts = bool(self._started) and (
            self._started == set(self._observed)
        )


def _prepare_raw_artifact_store_for_runtime() -> None:
    """Make raw-artifact configuration failure terminal for this public call."""

    try:
        prepare_structured_raw_artifact_store()
    except StructuredRawArtifactError as error:
        raise _StructuredFinalizationFailure(error) from error


def _unwrap_structured_finalization_failure(exc: Exception) -> Exception:
    """Return the original local failure rather than leaking a policy marker."""

    if isinstance(exc, _StructuredFinalizationFailure):
        return exc.cause
    return exc


def _build_validation_repair_message(exc: _StructuredValidationRetry) -> dict[str, str]:
    """Build a user message that tells the model what went wrong.

    The repair message includes the specific validation errors so the model
    can fix its output on the next attempt rather than guessing blindly.
    """

    error_lines = []
    for err in exc.validation_error.errors():
        loc = " -> ".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "unknown error")
        error_lines.append(f"  - {loc}: {msg}")
    errors_text = "\n".join(error_lines[:5])  # Cap at 5 errors to avoid prompt bloat.
    return {
        "role": "user",
        "content": (
            "Your previous response was valid JSON but failed schema validation:\n"
            f"{errors_text}\n\n"
            "Return a corrected response. If the selected discriminated-union "
            "variant cannot truthfully satisfy its required fields from the "
            "available information, choose another allowed variant instead of "
            "repeating the invalid one."
        ),
    }


def _validation_failure_class(error: ValidationError) -> AttemptFailureClass:
    """Classify missing required fields separately from other schema failures."""

    return (
        "missing_required"
        if any(issue.get("type") == "missing" for issue in error.errors())
        else "schema_validation"
    )


def _attempt_event(
    *,
    logical_call_id: str,
    trace_id: str,
    task: str,
    attempt: int,
    model: str,
    schema_hash: str,
    event_type: AttemptEventType,
    execution_path: Literal["native_schema", "responses_api"] = "native_schema",
    raw_content: str | None = None,
    raw_artifact_ref: str | None = None,
    validation_error: ValidationError | None = None,
    failure_class: AttemptFailureClass | None = None,
    validation_issues: tuple[StructuredValidationIssue, ...] = (),
    execution_error_type: str | None = None,
    recovery_decision: RecoveryDecision | None = None,
) -> StructuredAttemptEvent:
    """Build one typed native-schema attempt event without storing raw content."""

    issues = validation_issues
    if validation_error is not None:
        failure_class = _validation_failure_class(validation_error)
        issues = tuple(
            StructuredValidationIssue(
                location=tuple(issue.get("loc", ())),
                code=str(issue.get("type", "validation_error")),
                message=str(issue.get("msg", "validation failed"))[:500],
            )
            for issue in validation_error.errors()[:10]
        )
    return StructuredAttemptEvent(
        logical_call_id=logical_call_id,
        trace_id=trace_id,
        task=task,
        attempt_ordinal=attempt,
        model=model,
        execution_path=execution_path,
        schema_hash=schema_hash,
        event_type=event_type,
        raw_sha256=(
            _hashlib.sha256(raw_content.encode()).hexdigest()
            if raw_content is not None
            else None
        ),
        raw_artifact_ref=raw_artifact_ref,
        failure_class=failure_class,
        validation_issues=issues,
        execution_error_type=execution_error_type,
        recovery_decision=recovery_decision,
    )


def _received_attempt_event(
    *,
    logical_call_id: str,
    trace_id: str,
    task: str,
    attempt: int,
    model: str,
    schema_hash: str,
    raw_content: str,
    execution_path: Literal["native_schema", "responses_api"] = "native_schema",
) -> StructuredAttemptEvent:
    """Persist exact raw bytes first, then build their received metadata event."""

    artifact = write_structured_raw_artifact(
        logical_call_id,
        attempt,
        raw_content,
    )
    event = _attempt_event(
        logical_call_id=logical_call_id,
        trace_id=trace_id,
        task=task,
        attempt=attempt,
        model=model,
        schema_hash=schema_hash,
        event_type="received",
        execution_path=execution_path,
        raw_content=raw_content,
        raw_artifact_ref=(artifact.artifact_ref if artifact is not None else None),
    )
    if artifact is not None and event.raw_sha256 != artifact.raw_sha256:
        raise StructuredRawArtifactError(
            "Structured raw artifact hash contradicts its received event."
        )
    return event


def _execution_failure_class(error: Exception) -> AttemptFailureClass:
    """Classify a pre-response failure without retaining dynamic error text."""

    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    rate_limit_type = getattr(litellm, "RateLimitError", None)
    if isinstance(rate_limit_type, type) and isinstance(error, rate_limit_type):
        return "rate_limit"
    return "provider_execution"


def _record_execution_failure(
    *,
    error: Exception,
    logical_call_id: str,
    trace_id: str,
    task: str,
    attempt: int,
    model: str,
    schema_hash: str,
    execution_path: Literal["native_schema", "responses_api"] = "native_schema",
) -> None:
    """Persist one bounded pre-response failure without message or body."""

    event = _attempt_event(
        logical_call_id=logical_call_id,
        trace_id=trace_id,
        task=task,
        attempt=attempt,
        model=model,
        schema_hash=schema_hash,
        event_type="execution_failed",
        execution_path=execution_path,
        failure_class=_execution_failure_class(error),
        execution_error_type=type(error).__name__[:128],
    )
    record_structured_attempt_event(event)
    (
        status,
        provider_error_code,
        provider_request_id,
        gateway_request_id,
        retry_after_s,
    ) = _typed_failure_metadata(error)
    chain = tuple(
        item.__class__.__name__[:128]
        for item in (error, error.__cause__)
        if item is not None
    )
    confirmed = any(
        value is not None
        for value in (status, provider_error_code, provider_request_id, gateway_request_id)
    )
    timeout_message = str(error).lower()
    timeout_kind: TimeoutKind | None = (
        "client_logical_deadline"
        if isinstance(error, LLMLogicalDeadlineError)
        else (
            "client_attempt_deadline"
            if isinstance(error, TimeoutError) and "client deadline" in timeout_message
            else (
                "client_attempt_safety"
                if isinstance(error, TimeoutError) and "safety deadline" in timeout_message
                else ("unknown" if isinstance(error, TimeoutError) else None)
            )
        )
    )
    if not _io_log._logging_enabled():
        return
    record_attempt_diagnostic(AttemptDiagnosticEnvelope(
        attempt_event_id=event.event_id, logical_call_id=logical_call_id,
        trace_id=trace_id, task=task, attempt_ordinal=attempt,
        phase="awaiting_response", origin=("gateway_or_provider_response" if confirmed else "transport"),
        attribution=("gateway_or_provider_confirmed" if confirmed else "client_observed_only"),
        exception_chain=chain, exception_fingerprint=exception_fingerprint(chain),
        http_status=status if isinstance(status, int) else None,
        provider_error_code=provider_error_code,
        provider_request_id=provider_request_id,
        gateway_request_id=gateway_request_id,
        retry_after_s=retry_after_s,
        timeout_kind=timeout_kind,
        response_outcome=("empty_content" if isinstance(error, _EmptyStructuredContentError) else None),
        sanitized_summary=("empty structured content observed after response" if isinstance(error, _EmptyStructuredContentError) else ("typed gateway/provider response failure" if confirmed else "client observed pre-response execution failure")),
    ))


def _typed_failure_metadata(
    error: Exception,
) -> tuple[int | None, str | None, str | None, str | None, float | None]:
    """Extract bounded adapter metadata without parsing arbitrary error prose."""

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(error, "headers", None)

    def _header(name: str) -> str | None:
        if headers is None or not hasattr(headers, "get"):
            return None
        value = headers.get(name)
        if not isinstance(value, str):
            return None
        return value if _re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", value) else None

    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        status = getattr(error, "status_code", None)
    if not isinstance(status, int) or not 100 <= status <= 599:
        status = None

    code = getattr(error, "code", None)
    provider_error_code = (
        code
        if isinstance(code, str) and _re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", code)
        else None
    )
    provider_request_id = _header("x-provider-request-id") or _header("provider-request-id")
    gateway_request_id = _header("x-request-id") or _header("request-id")
    retry_after_s: float | None = None
    for value in (getattr(error, "retry_after", None), _header("retry-after")):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            retry_after_s = parsed
            break
    return status, provider_error_code, provider_request_id, gateway_request_id, retry_after_s


def _provider_schema_validation_raw(error: Exception) -> str | None:
    """Return raw content carried by LiteLLM's pre-return schema exception.

    LiteLLM may validate ``response_format`` internally and raise before
    ``completion`` returns. That exception still represents a provider generation
    attempt and carries the original response on ``raw_response``. Restrict the
    extraction to LiteLLM's typed exception so unrelated errors with similarly
    named attributes cannot be misclassified as generation attempts.
    """

    import litellm

    error_type = getattr(litellm, "JSONSchemaValidationError", None)
    if not isinstance(error_type, type) or not isinstance(error, error_type):
        return None
    raw_response = getattr(error, "raw_response", None)
    return raw_response if isinstance(raw_response, str) else None


def _record_provider_schema_validation_failure(
    *,
    error: Exception,
    logical_call_id: str,
    trace_id: str,
    task: str,
    attempt: int,
    model: str,
    schema_hash: str,
) -> bool:
    """Persist a LiteLLM pre-return validation failure as a complete attempt."""

    raw_content = _provider_schema_validation_raw(error)
    if raw_content is None:
        return False
    record_structured_attempt_event(_received_attempt_event(
        logical_call_id=logical_call_id, trace_id=trace_id, task=task,
        attempt=attempt, model=model, schema_hash=schema_hash,
        raw_content=raw_content,
    ))
    record_structured_attempt_event(_attempt_event(
        logical_call_id=logical_call_id, trace_id=trace_id, task=task,
        attempt=attempt, model=model, schema_hash=schema_hash,
        event_type="validation_failed", failure_class="schema_validation",
        validation_issues=(StructuredValidationIssue(
            location=(),
            code="provider_json_schema_validation",
            message="Provider response failed LiteLLM JSON Schema validation.",
        ),),
    ))
    return True


def _record_response_parse_failure(
    *,
    logical_call_id: str,
    trace_id: str,
    task: str,
    attempt: int,
    model: str,
    schema_hash: str,
    execution_path: Literal["native_schema", "responses_api"] = "native_schema",
) -> None:
    """Classify malformed received JSON as validation, not provider execution."""

    record_structured_attempt_event(
        _attempt_event(
            logical_call_id=logical_call_id,
            trace_id=trace_id,
            task=task,
            attempt=attempt,
            model=model,
            schema_hash=schema_hash,
            event_type="validation_failed",
            execution_path=execution_path,
            failure_class="schema_validation",
            validation_issues=(
                StructuredValidationIssue(
                    location=(),
                    code="json_invalid",
                    message="Provider response could not be parsed as valid JSON.",
                ),
            ),
        )
    )


def _base_model_name(model: str) -> str:
    """Return the provider-agnostic lowercase model name."""
    return model.lower().rsplit("/", 1)[-1]


def _is_gpt5_family_model(model: str) -> bool:
    """Return whether a model belongs to the GPT-5 family."""
    return _base_model_name(model).startswith("gpt-5")


def _is_invalid_json_schema_error(error: Exception) -> bool:
    """Return whether an exception indicates provider-side schema rejection."""
    message = str(error).lower()
    return "invalid_json_schema" in message or (
        "invalid schema" in message and "json_schema" in message
    )


def _raise_if_unsupported_gpt5_structured_schema(
    *,
    model: str,
    error: Exception,
    caller: str,
) -> None:
    """Raise a typed capability error for unsupported GPT-5 structured schema paths.

    GPT-5 family models can be selected for structured workloads, but some
    direct/provider-specific JSON-schema transports reject the supplied schema at
    request-validation time. When that happens, callers need a clear,
    non-retryable capability failure rather than a vague provider error or a
    fallback that obscures the real incompatibility.
    """
    if not _is_gpt5_family_model(model) or not _is_invalid_json_schema_error(error):
        return
    _raise_gpt5_structured_schema_capability_error(model=model, error=error, caller=caller)


def _raise_gpt5_structured_schema_capability_error(
    *,
    model: str,
    error: Exception,
    caller: str,
) -> NoReturn:
    """Raise the canonical GPT-5 structured-schema compatibility error."""
    raise LLMCapabilityError(
        f"{caller}: provider rejected structured JSON-schema output for GPT-5-family model "
        f"{model}. llm_client does not currently support this transport/schema combination "
        "reliably. Use a different task/model, or change routing/provider strategy.",
        original=error,
    ) from error


def _native_provider_schema(
    response_model: type[BaseModel],
    *,
    model: str,
) -> dict[str, Any]:
    """Build a strict native schema, resolving ref siblings for OpenRouter."""

    if model.startswith("openrouter/"):
        schema = _client._strict_openai_response_model_schema(response_model)
        return cast(
            dict[str, Any],
            _client._openrouter_compatible_strict_json_schema(schema),
        )
    return cast(
        dict[str, Any],
        _client._strict_json_schema(response_model.model_json_schema()),
    )


def _call_llm_structured_impl(
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[T],
    *,
    timeout: int = 60,
    logical_timeout: float | None = None,
    num_retries: int = 2,
    reasoning_effort: str | None = None,
    api_base: str | None = None,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: list[str] | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    cache: CachePolicy | None = None,
    retry: RetryPolicy | None = None,
    fallback_models: list[str] | None = None,
    on_fallback: Callable[[str, Exception, str], None] | None = None,
    hooks: Hooks | None = None,
    config: ClientConfig | None = None,
    structured_output_policy: StructuredOutputPolicy | None = None,
    **kwargs: Any,
) -> tuple[T, LLMCallResult]:
    """Run the synchronous structured-call runtime behind ``client.call_llm_structured``."""
    reasoning_effort = (
        str(reasoning_effort).strip().lower()
        if reasoning_effort is not None
        else None
    )
    time = _client.time
    logger = _client.logger
    litellm = _client.litellm
    _rate_limit = _client._rate_limit
    _check_model_deprecation = _client._check_model_deprecation
    _normalize_prompt_ref = _client._normalize_prompt_ref
    _require_tags = _client._require_tags
    _normalize_timeout = _client._normalize_timeout
    _check_budget = _client._check_budget
    _resolve_call_plan = _client._resolve_call_plan
    _routing_policy_label = _client._routing_policy_label
    _is_agent_model = _client._is_agent_model
    _finalize_result = _client._finalize_result
    _build_routing_trace = _client._build_routing_trace
    _base_log_call_event = _client._log_call_event
    _effective_retry = _client._effective_retry
    _resolve_api_base_for_model = _client._resolve_api_base_for_model
    _background_mode_for_model = _client._background_mode_for_model
    _is_responses_api_model = _client._is_responses_api_model
    _cache_key = _client._cache_key
    exponential_backoff = _client.exponential_backoff
    _strict_json_schema = _client._strict_json_schema
    _strict_openai_response_model_schema = _client._strict_openai_response_model_schema
    _provider_compatible_discriminated_union_schema = (
        _client._provider_compatible_discriminated_union_schema
    )
    _openrouter_compatible_strict_json_schema = _client._openrouter_compatible_strict_json_schema
    _prepare_responses_kwargs = _client._prepare_responses_kwargs
    _extract_responses_usage = _client._extract_responses_usage
    _parse_cost_result = _client._parse_cost_result
    _compute_responses_cost = _client._compute_responses_cost
    _build_structured_call_result = _client._build_structured_call_result
    run_sync_with_retry = _client.run_sync_with_retry
    _check_retryable = _client._check_retryable
    _compute_retry_delay = _client._compute_retry_delay
    _maybe_retry_with_openrouter_key_rotation = _client._maybe_retry_with_openrouter_key_rotation
    _prepare_call_kwargs = _client._prepare_call_kwargs
    _first_choice_or_empty_error = _client._first_choice_or_empty_error
    _extract_usage = _client._extract_usage
    _compute_cost = _client._compute_cost
    _is_schema_error = _client._is_schema_error
    _NativeSchemaFallback = _client._NativeSchemaFallback
    run_sync_with_fallback = _client.run_sync_with_fallback
    wrap_error = _client.wrap_error

    _check_model_deprecation(model)
    output_policy = structured_output_policy or StructuredOutputPolicy()
    require_native_json_schema = output_policy.mode == "require_native_json_schema"
    cfg = config or ClientConfig.from_env()
    _log_t0 = time.monotonic()
    task = kwargs.pop("task", None)
    trace_id = kwargs.pop("trace_id", None)
    max_budget: float | None = kwargs.pop("max_budget", None)
    budget_scope_trace_id: str | None = kwargs.pop("budget_scope_trace_id", None)
    prompt_ref = _normalize_prompt_ref(kwargs.pop("prompt_ref", None))
    model_policy = str(kwargs.pop("model_policy", "enforce_allowlist"))
    model_justification = kwargs.pop("model_justification", None)
    task, trace_id, max_budget, _entry_warnings = _require_tags(
        task, trace_id, max_budget, caller="call_llm_structured",
    )
    _logical_call_id = str(kwargs.pop("_lifecycle_logical_call_id", "")).strip() or uuid4().hex
    def _log_call_event(**event: Any) -> None:
        """Bind the returned result and terminal row to one attempt history."""
        result = event.get("result")
        if isinstance(result, LLMCallResult):
            result.logical_call_id = _logical_call_id
        _base_log_call_event(**event, logical_call_id=_logical_call_id)
        _io_log.record_call_lifecycle_event({"event_id": uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(), "logical_call_id": _logical_call_id, "trace_id": trace_id, "task": task, "phase": "completed" if isinstance(result, LLMCallResult) else "failed", "requested_model": model, "resolved_model": result.model if isinstance(result, LLMCallResult) else None, "call_kind": "structured", "error_type": type(event["error"]).__name__ if event.get("error") is not None else None})
    timeout = _normalize_timeout(
        timeout,
        caller="call_llm_structured",
        warning_sink=_entry_warnings,
        logger=logger,
        log_policy_once_enabled=True,
    )
    logical_timeout = _normalize_logical_timeout(logical_timeout)
    deadline_at = _logical_deadline_at(logical_timeout)

    def _attempt_timeout() -> tuple[float, bool]:
        return _effective_attempt_timeout(timeout, deadline_at=deadline_at)

    _check_budget(
        trace_id,
        max_budget,
        budget_scope_trace_id=budget_scope_trace_id,
        warning_sink=_entry_warnings,
    )
    public_kwargs = _client._strip_llm_internal_kwargs(dict(kwargs))
    snapshot_public_kwargs = dict(public_kwargs)
    snapshot_public_kwargs["model_policy"] = model_policy
    if logical_timeout is not None:
        snapshot_public_kwargs["logical_timeout"] = logical_timeout
    if model_justification is not None:
        snapshot_public_kwargs["model_justification"] = model_justification
    _inject_langfuse_metadata(kwargs, task=task, trace_id=trace_id)
    r = _effective_retry(retry, num_retries, base_delay, max_delay, retry_on, on_retry)
    from llm_client.observability.replay import build_call_snapshot

    call_snapshot = build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model=model,
        messages=messages,
        prompt_ref=prompt_ref,
        max_budget=max_budget,
        timeout=timeout,
        num_retries=num_retries,
        reasoning_effort=reasoning_effort,
        api_base=api_base,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_on=retry_on,
        fallback_models=fallback_models,
        public_kwargs=snapshot_public_kwargs,
        retry_policy=r,
        cache_policy=cache,
        structured_output_mode=output_policy.mode,
        response_model=response_model,
    )
    plan = _resolve_call_plan(
        model=model,
        fallback_models=fallback_models,
        api_base=api_base,
        config=cfg,
        model_policy=model_policy,
        model_justification=model_justification,
        reasoning_effort=reasoning_effort,
    )
    models = plan.models
    routing_policy = str(plan.routing_trace.get("routing_policy", _routing_policy_label(cfg)))
    model_policy_trace = plan.routing_trace.get("model_policy")
    if plan.primary_model.startswith("codex"):
        legacy_effort = public_kwargs.get("model_reasoning_effort")
        if (
            legacy_effort is not None
            and str(legacy_effort).strip().lower() != reasoning_effort
        ):
            raise LLMConfigurationError(
                "reasoning_effort conflicts with model_reasoning_effort for Codex"
            )
        public_kwargs["model_reasoning_effort"] = reasoning_effort

    if _is_agent_model(model):
        if require_native_json_schema:
            capability_error = LLMCapabilityError(
                f"Model {model} uses an Agent SDK structured path, not provider-native JSON schema."
            )
            _log_call_event(
                model=model,
                messages=messages,
                error=capability_error,
                latency_s=time.monotonic() - _log_t0,
                caller="call_llm_structured",
                task=task,
                trace_id=trace_id,
                prompt_ref=prompt_ref,
                call_snapshot=call_snapshot,
                execution_path="error",
                retry_count=None,
            )
            raise capability_error
        from llm_client.sdk.agents import _route_call_structured

        if hooks and hooks.before_call:
            hooks.before_call(model, messages, public_kwargs)
        attempt_timeout, logical_cap = _attempt_timeout()
        parsed, llm_result = _run_sync_with_deadline(
            lambda: _route_call_structured(
                model,
                messages,
                response_model,
                # The legacy SDK annotation is integral, but its runtime accepts
                # fractional seconds and the precise remaining cap must not round up.
                timeout=cast(int, attempt_timeout),
                **public_kwargs,
            ),
            timeout=attempt_timeout,
            logical_cap=logical_cap,
        )
        llm_result = _finalize_result(
            llm_result,
            requested_model=model,
            resolved_model=llm_result.resolved_model,
            routing_trace=_build_routing_trace(
                requested_model=model,
                attempted_models=[plan.primary_model],
                selected_model=llm_result.resolved_model,
                requested_api_base=api_base,
                effective_api_base=api_base,
                routing_policy=routing_policy,
                model_policy=model_policy_trace,
            ),
        )
        if hooks and hooks.after_call:
            hooks.after_call(llm_result)
        _log_call_event(
            model=model,
            messages=messages,
            result=llm_result,
            latency_s=time.monotonic() - _log_t0,
            caller="call_llm_structured",
            task=task,
            trace_id=trace_id,
            prompt_ref=prompt_ref,
            call_snapshot=call_snapshot,
            execution_path="agent_sdk",
            retry_count=0,
            response_format_type="agent_sdk",
        )
        return cast(T, parsed), llm_result
    _warnings: list[str] = list(_entry_warnings)
    _model_fqn = f"{response_model.__module__}.{response_model.__qualname__}"
    last_model_attempted = model
    next_structured_attempt_ordinal = 0
    structured_attempt_costs = _AttemptCostLedger()

    def _execute_model(model_idx: int, current_model: str) -> tuple[T, LLMCallResult]:
        nonlocal last_model_attempted, next_structured_attempt_ordinal
        last_model_attempted = current_model
        current_api_base = _resolve_api_base_for_model(current_model, api_base, cfg)
        background_mode = _background_mode_for_model(
            model=current_model,
            use_responses=_is_responses_api_model(current_model),
            reasoning_effort=reasoning_effort,
        )
        key: str | None = None
        if cache is not None:
            key = _cache_key(
                current_model,
                messages,
                response_model=_model_fqn,
                reasoning_effort=reasoning_effort,
                **public_kwargs,
            )
            cached = cache.get(key)
            if cached is not None:
                reparsed = response_model.model_validate_json(cached.content)
                cached_result = _finalize_result(
                    cached,
                    cache_hit=True,
                    requested_model=model,
                    resolved_model=current_model,
                    routing_trace=_build_routing_trace(
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        selected_model=current_model,
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    ),
                )
                _log_call_event(
                    model=current_model,
                    messages=messages,
                    result=cached_result,
                    latency_s=time.monotonic() - _log_t0,
                    caller="call_llm_structured",
                    task=task,
                    trace_id=trace_id,
                    prompt_ref=prompt_ref,
                    call_snapshot=call_snapshot,
                    execution_path="responses_api",
                    retry_count=0,
                    response_format_type="json_schema",
                )
                return reparsed, cached_result

        if hooks and hooks.before_call:
            hooks.before_call(current_model, messages, public_kwargs)

        backoff_fn = r.backoff or exponential_backoff

        if _is_responses_api_model(current_model):
            _prepare_raw_artifact_store_for_runtime()
            schema = _provider_compatible_discriminated_union_schema(
                _strict_openai_response_model_schema(response_model)
            )
            if current_model.startswith("openrouter/"):
                schema = _openrouter_compatible_strict_json_schema(schema)
            _responses_schema_hash = _hashlib.sha256(
                _json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()[:16]
            resp_kwargs = _prepare_responses_kwargs(
                current_model,
                messages,
                timeout=timeout,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            resp_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": _provider_schema_name(response_model),
                    "schema": schema,
                    "strict": True,
                }
            }

            response_input = str(resp_kwargs["input"])
            pending_repair_message: dict[str, str] | None = None
            responses_recovery_pending: set[int] = set()
            responses_attempt_ordinals: dict[int, int] = {}

            def _responses_attempt_ordinal(local_attempt: int) -> int:
                """Assign one logical-call-global ordinal to a Responses attempt."""

                nonlocal next_structured_attempt_ordinal
                if local_attempt not in responses_attempt_ordinals:
                    responses_attempt_ordinals[local_attempt] = (
                        next_structured_attempt_ordinal
                    )
                    next_structured_attempt_ordinal += 1
                return responses_attempt_ordinals[local_attempt]

            def _record_responses_recovery(
                attempt: int,
                _error: Exception,
                decision: Literal["retry", "exhausted"],
            ) -> None:
                """Persist the retry kernel's actual Responses disposition once."""

                logical_attempt = _responses_attempt_ordinal(attempt)
                if logical_attempt not in responses_recovery_pending:
                    return
                responses_recovery_pending.remove(logical_attempt)
                recovery_decision: RecoveryDecision = decision
                if decision == "exhausted" and model_idx < len(models) - 1:
                    recovery_decision = "fallback"
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_responses_schema_hash,
                        event_type="recovery_decided",
                        execution_path="responses_api",
                        recovery_decision=recovery_decision,
                    )
                )

            def _invoke_responses_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                nonlocal pending_repair_message
                logical_attempt = _responses_attempt_ordinal(attempt)
                structured_attempt_costs.mark_started(logical_attempt)
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_responses_schema_hash,
                        event_type="started",
                        execution_path="responses_api",
                    )
                )
                call_kwargs = dict(resp_kwargs)
                if pending_repair_message is not None:
                    call_kwargs["input"] = (
                        f"{response_input}\n\nUser: {pending_repair_message['content']}"
                    )
                    pending_repair_message = None
                    logger.info(
                        "call_llm_structured: appended validation repair message for responses attempt %d",
                        attempt,
                    )

                attempt_received = False
                attempt_validated = False

                def provider_call() -> Any:
                    with _rate_limit.acquire(current_model):
                        return litellm.responses(**call_kwargs)

                try:
                    attempt_timeout, logical_cap = _attempt_timeout()
                    call_kwargs["timeout"] = attempt_timeout
                    response = _run_sync_with_deadline(
                        provider_call,
                        timeout=attempt_timeout,
                        logical_cap=logical_cap,
                    )
                    raw_content = getattr(response, "output_text", None) or ""
                    if not raw_content.strip():
                        raise _EmptyStructuredContentError(
                            "Empty content from LLM (responses API structured)"
                        )
                    record_structured_attempt_event(
                        _received_attempt_event(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash,
                            raw_content=raw_content,
                            execution_path="responses_api",
                        )
                    )
                    attempt_received = True
                    usage = _extract_responses_usage(response)
                    attempt_cost, attempt_cost_source = _parse_cost_result(
                        _compute_responses_cost(response, usage),
                        default_source="computed",
                    )
                    structured_attempt_costs.record_response(
                        logical_attempt,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                    )
                    try:
                        parsed = _robust_validate_json(response_model, raw_content)
                    except ValidationError as validation_error:
                        record_structured_attempt_event(
                            _attempt_event(
                                logical_call_id=_logical_call_id,
                                trace_id=trace_id,
                                task=task,
                                attempt=logical_attempt,
                                model=current_model,
                                schema_hash=_responses_schema_hash,
                                event_type="validation_failed",
                                execution_path="responses_api",
                                validation_error=validation_error,
                            )
                        )
                        responses_recovery_pending.add(logical_attempt)
                        retry_exc = _StructuredValidationRetry(
                            raw_content, validation_error
                        )
                        pending_repair_message = _build_validation_repair_message(
                            retry_exc
                        )
                        raise retry_exc from validation_error
                    except Exception as parse_error:
                        _record_response_parse_failure(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash,
                            execution_path="responses_api",
                        )
                        responses_recovery_pending.add(logical_attempt)
                        raise _StructuredParseRetry(
                            "Provider response was not valid JSON."
                        ) from parse_error
                    attempt_validated = True
                    record_structured_attempt_event(
                        _attempt_event(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash,
                            event_type="validated",
                            execution_path="responses_api",
                        )
                    )

                    if attempt > 0:
                        logger.info(
                            "call_llm_structured (responses) succeeded after %d retries",
                            attempt,
                        )

                    llm_result = _build_structured_call_result(
                        parsed=parsed,
                        usage=usage,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                        current_model=current_model,
                        finish_reason="stop",
                        raw_response=response,
                        warnings=_warnings,
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    )
                    structured_attempt_costs.apply(llm_result)
                    if hooks and hooks.after_call:
                        hooks.after_call(llm_result)
                    if cache is not None and key is not None:
                        cache.set(key, llm_result)
                    _log_call_event(
                        model=current_model,
                        messages=messages,
                        result=llm_result,
                        latency_s=time.monotonic() - _log_t0,
                        caller="call_llm_structured",
                        task=task,
                        trace_id=trace_id,
                        prompt_ref=prompt_ref,
                        call_snapshot=call_snapshot,
                        execution_path="responses_api",
                        retry_count=attempt,
                        schema_hash=_responses_schema_hash,
                        response_format_type="responses_api",
                    )
                    return parsed, llm_result
                except Exception as exc:
                    if attempt_validated:
                        raise _StructuredFinalizationFailure(exc) from exc
                    if isinstance(exc, StructuredRawArtifactError):
                        raise _StructuredFinalizationFailure(exc) from exc
                    if attempt_received and not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ):
                        raise _StructuredFinalizationFailure(exc) from exc
                    if not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ):
                        _record_execution_failure(
                            error=exc,
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash,
                            execution_path="responses_api",
                        )
                        responses_recovery_pending.add(logical_attempt)
                    _raise_if_unsupported_gpt5_structured_schema(
                        model=current_model,
                        error=exc,
                        caller="call_llm_structured",
                    )
                    raise

            def _on_responses_error(exc: Exception, attempt: int) -> None:
                if hooks and hooks.on_error:
                    try:
                        hooks.on_error(
                            _unwrap_structured_finalization_failure(exc), attempt
                        )
                    except Exception as hook_error:
                        if isinstance(exc, _StructuredFinalizationFailure):
                            raise _StructuredFinalizationFailure(hook_error) from exc
                        raise

            return cast(tuple[T, LLMCallResult], run_sync_with_retry(
                caller="call_llm_structured",
                model=current_model,
                max_retries=r.max_retries,
                invoke=_invoke_responses_attempt,
                should_retry=lambda exc: not isinstance(
                    exc, _StructuredFinalizationFailure
                )
                and (
                    isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    )
                    or _check_retryable(exc, r)
                ),
                compute_delay=lambda attempt, exc: _compute_retry_delay(
                    attempt=attempt,
                    error=exc,
                    policy=r,
                    backoff_fn=backoff_fn,
                ),
                warning_sink=_warnings,
                logger=logger,
                on_error=_on_responses_error,
                on_retry=r.on_retry,
                on_decision=_record_responses_recovery,
                deadline_at=deadline_at,
                maybe_retry_hook=lambda exc, attempt, max_retries: (
                    False
                    if isinstance(exc, _StructuredFinalizationFailure)
                    else _maybe_retry_with_openrouter_key_rotation(
                        error=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        current_model=current_model,
                        current_api_base=current_api_base,
                        user_kwargs=public_kwargs,
                        warning_sink=_warnings,
                        on_retry=r.on_retry,
                        caller="call_llm_structured",
                    )
                ),
            ))

        supports_schema = _model_supports_native_schema(current_model)
        _native_schema_failed = False
        if require_native_json_schema and not supports_schema:
            raise LLMCapabilityError(
                f"Model {current_model} does not support native JSON schema; "
                "strict structured-output policy forbids Instructor fallback."
            )
        if supports_schema:
            _prepare_raw_artifact_store_for_runtime()
            schema = _native_provider_schema(response_model, model=current_model)
            base_kwargs = _prepare_call_kwargs(
                current_model,
                messages,
                timeout=timeout,
                num_retries=r.max_retries,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            _schema_hash = _hashlib.sha256(
                _json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()[:16]
            base_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _provider_schema_name(response_model),
                    "schema": schema,
                    "strict": True,
                },
            }

            _pending_repair_message: dict[str, str] | None = None
            _recovery_pending: set[int] = set()
            _attempt_ordinals: dict[int, int] = {}

            def _native_attempt_ordinal(local_attempt: int) -> int:
                """Assign one contiguous ordinal when an attempt actually starts."""

                nonlocal next_structured_attempt_ordinal
                if local_attempt not in _attempt_ordinals:
                    _attempt_ordinals[local_attempt] = next_structured_attempt_ordinal
                    next_structured_attempt_ordinal += 1
                return _attempt_ordinals[local_attempt]

            def _record_native_recovery(
                attempt: int,
                error: Exception,
                decision: Literal["retry", "exhausted"],
            ) -> None:
                """Persist the retry kernel's actual disposition exactly once."""

                logical_attempt = _native_attempt_ordinal(attempt)
                if logical_attempt not in _recovery_pending:
                    return
                _recovery_pending.remove(logical_attempt)
                recovery_decision: RecoveryDecision = decision
                if decision == "exhausted" and (
                    (isinstance(error, _NativeSchemaFallback) and not require_native_json_schema)
                    or model_idx < len(models) - 1
                ):
                    recovery_decision = "fallback"
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_schema_hash,
                        event_type="recovery_decided",
                        recovery_decision=recovery_decision,
                    )
                )

            def _invoke_native_schema_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                nonlocal _pending_repair_message
                logical_attempt = _native_attempt_ordinal(attempt)
                structured_attempt_costs.mark_started(logical_attempt)
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_schema_hash,
                        event_type="started",
                    )
                )
                if _pending_repair_message is not None:
                    base_kwargs["messages"] = list(base_kwargs["messages"]) + [_pending_repair_message]
                    _pending_repair_message = None
                    logger.info("call_llm_structured: appended validation repair message for attempt %d", attempt)
                attempt_validated = False

                def provider_call() -> Any:
                    with _rate_limit.acquire(current_model):
                        return litellm.completion(**base_kwargs)

                try:
                    attempt_timeout, logical_cap = _attempt_timeout()
                    base_kwargs["timeout"] = attempt_timeout
                    response = _run_sync_with_deadline(
                        provider_call,
                        timeout=attempt_timeout,
                        logical_cap=logical_cap,
                    )
                    first_choice = _first_choice_or_empty_error(
                        response,
                        model=current_model,
                        provider="litellm_completion_structured",
                    )
                    raw_content = first_choice.message.content or ""
                    if not raw_content.strip():
                        raise _EmptyStructuredContentError("Empty content from LLM (native JSON schema structured)")
                    record_structured_attempt_event(_received_attempt_event(
                        logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                        attempt=logical_attempt, model=current_model, schema_hash=_schema_hash,
                        raw_content=raw_content,
                    ))
                    attempt_cost, attempt_cost_source = _parse_cost_result(
                        _compute_cost(response)
                    )
                    structured_attempt_costs.record_response(
                        logical_attempt,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                    )
                    try:
                        parsed = _robust_validate_json(response_model, raw_content)
                    except ValidationError as ve:
                        record_structured_attempt_event(_attempt_event(
                            logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                            attempt=logical_attempt, model=current_model, schema_hash=_schema_hash,
                            event_type="validation_failed", validation_error=ve,
                        ))
                        _recovery_pending.add(logical_attempt)
                        retry_exc = _StructuredValidationRetry(raw_content, ve)
                        _pending_repair_message = _build_validation_repair_message(retry_exc)
                        raise retry_exc from ve
                    except Exception as parse_error:
                        _record_response_parse_failure(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_schema_hash,
                        )
                        _recovery_pending.add(logical_attempt)
                        raise _StructuredParseRetry(
                            "Provider response was not valid JSON."
                        ) from parse_error
                    attempt_validated = True
                    record_structured_attempt_event(_attempt_event(
                        logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                        attempt=logical_attempt, model=current_model, schema_hash=_schema_hash,
                        event_type="validated",
                    ))
                    usage = _extract_usage(response)
                    cost, cost_source = attempt_cost, attempt_cost_source
                    finish_reason: str = first_choice.finish_reason or "stop"

                    if attempt > 0:
                        logger.info("call_llm_structured (native schema) succeeded after %d retries", attempt)

                    llm_result = _build_structured_call_result(
                        parsed=parsed,
                        usage=usage,
                        cost=cost,
                        cost_source=cost_source,
                        current_model=current_model,
                        finish_reason=finish_reason,
                        raw_response=response,
                        warnings=_warnings,
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    )
                    structured_attempt_costs.apply(llm_result)
                    if hooks and hooks.after_call:
                        hooks.after_call(llm_result)
                    if cache is not None and key is not None:
                        cache.set(key, llm_result)
                    _log_call_event(
                        model=current_model,
                        messages=messages,
                        result=llm_result,
                        latency_s=time.monotonic() - _log_t0,
                        caller="call_llm_structured",
                        task=task,
                        trace_id=trace_id,
                        prompt_ref=prompt_ref,
                        call_snapshot=call_snapshot,
                        execution_path="native_schema",
                        retry_count=attempt,
                        schema_hash=_schema_hash,
                        response_format_type="json_schema",
                    )
                    _record_openrouter_native_route_observation(
                        result=llm_result,
                        provider_schema=schema,
                        response_model=response_model,
                    )
                    return parsed, llm_result
                except Exception as exc:
                    if attempt_validated:
                        raise _StructuredFinalizationFailure(exc) from exc
                    if isinstance(exc, StructuredRawArtifactError):
                        raise _StructuredFinalizationFailure(exc) from exc
                    try:
                        provider_validation = _record_provider_schema_validation_failure(
                            error=exc, logical_call_id=_logical_call_id,
                            trace_id=trace_id, task=task, attempt=logical_attempt,
                            model=current_model, schema_hash=_schema_hash,
                        )
                    except StructuredRawArtifactError as artifact_error:
                        raise _StructuredFinalizationFailure(artifact_error) from artifact_error
                    if provider_validation:
                        _recovery_pending.add(logical_attempt)
                    elif not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ) and not attempt_validated:
                        _record_execution_failure(
                            error=exc,
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_schema_hash,
                        )
                        _recovery_pending.add(logical_attempt)
                    _raise_if_unsupported_gpt5_structured_schema(
                        model=current_model,
                        error=exc,
                        caller="call_llm_structured",
                    )
                    if _is_schema_error(exc):
                        raise _NativeSchemaFallback(str(exc)) from exc
                    raise

            def _on_native_schema_error(exc: Exception, attempt: int) -> None:
                if isinstance(exc, _NativeSchemaFallback):
                    return
                if hooks and hooks.on_error:
                    try:
                        hooks.on_error(_unwrap_structured_finalization_failure(exc), attempt)
                    except Exception as hook_error:
                        if isinstance(exc, _StructuredFinalizationFailure):
                            raise _StructuredFinalizationFailure(hook_error) from exc
                        raise

            try:
                return cast(tuple[T, LLMCallResult], run_sync_with_retry(
                    caller="call_llm_structured",
                    model=current_model,
                    max_retries=r.max_retries,
                    invoke=_invoke_native_schema_attempt,
                    should_retry=lambda exc: not isinstance(exc, _StructuredFinalizationFailure)
                    and (
                        isinstance(
                            exc, (_StructuredValidationRetry, _StructuredParseRetry)
                        )
                        or (not isinstance(exc, _NativeSchemaFallback) and _check_retryable(exc, r))
                    ),
                    compute_delay=lambda attempt, exc: _compute_retry_delay(
                        attempt=attempt,
                        error=exc,
                        policy=r,
                        backoff_fn=backoff_fn,
                    ),
                    warning_sink=_warnings,
                    logger=logger,
                    on_error=_on_native_schema_error,
                    on_retry=r.on_retry,
                    on_decision=_record_native_recovery,
                    deadline_at=deadline_at,
                    maybe_retry_hook=lambda exc, attempt, max_retries: (
                        False if isinstance(exc, (_NativeSchemaFallback, _StructuredFinalizationFailure)) else _maybe_retry_with_openrouter_key_rotation(
                            error=exc,
                            attempt=attempt,
                            max_retries=max_retries,
                            current_model=current_model,
                            current_api_base=current_api_base,
                            user_kwargs=public_kwargs,
                            warning_sink=_warnings,
                            on_retry=r.on_retry,
                            caller="call_llm_structured",
                        )
                    ),
                ))
            except _NativeSchemaFallback as schema_error:
                if require_native_json_schema:
                    raise LLMCapabilityError(
                        f"Provider rejected native JSON schema for model {current_model}; "
                        "strict structured-output policy forbids Instructor fallback.",
                        original=schema_error,
                    ) from schema_error
                logger.warning(
                    "Native JSON schema rejected by provider (%s), falling back to instructor: %s",
                    current_model,
                    schema_error,
                )
                _native_schema_failed = True

        if not supports_schema or _native_schema_failed:
            client = _instructor_from_litellm(litellm.completion)
            base_kwargs = _prepare_call_kwargs(
                current_model,
                messages,
                timeout=timeout,
                num_retries=r.max_retries,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            call_kwargs = {**base_kwargs, "response_model": response_model, "max_retries": 2}
            _instructor_schema_hash = _hashlib.sha256(
                _json.dumps(response_model.model_json_schema(), sort_keys=True).encode()
            ).hexdigest()[:16]

            def _invoke_instructor_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                attempt_timeout, logical_cap = _attempt_timeout()
                call_kwargs["timeout"] = attempt_timeout
                parsed, completion_response = _run_sync_with_deadline(
                    lambda: client.chat.completions.create_with_completion(**call_kwargs),
                    timeout=attempt_timeout,
                    logical_cap=logical_cap,
                )

                usage = _extract_usage(completion_response)
                cost, cost_source = _parse_cost_result(_compute_cost(completion_response))
                completion_choice = _first_choice_or_empty_error(
                    completion_response,
                    model=current_model,
                    provider="instructor_completion_structured",
                )
                finish_reason = completion_choice.finish_reason or ""

                if attempt > 0:
                    logger.info("call_llm_structured succeeded after %d retries", attempt)

                llm_result = _build_structured_call_result(
                    parsed=parsed,
                    usage=usage,
                    cost=cost,
                    cost_source=cost_source,
                    current_model=current_model,
                    finish_reason=finish_reason,
                    raw_response=completion_response,
                    warnings=_warnings,
                    requested_model=model,
                    attempted_models=models[:model_idx + 1],
                    requested_api_base=api_base,
                    effective_api_base=current_api_base,
                    background_mode=background_mode,
                    routing_policy=routing_policy,
                    model_policy=model_policy_trace,
                )

                if hooks and hooks.after_call:
                    hooks.after_call(llm_result)
                if cache is not None and key is not None:
                    cache.set(key, llm_result)
                _log_call_event(
                    model=current_model,
                    messages=messages,
                    result=llm_result,
                    latency_s=time.monotonic() - _log_t0,
                    caller="call_llm_structured",
                    task=task,
                    trace_id=trace_id,
                    prompt_ref=prompt_ref,
                    call_snapshot=call_snapshot,
                    execution_path="instructor",
                    retry_count=attempt,
                    schema_hash=_instructor_schema_hash,
                    response_format_type="instructor",
                )
                return parsed, llm_result

            return cast(tuple[T, LLMCallResult], run_sync_with_retry(
                caller="call_llm_structured",
                model=current_model,
                max_retries=r.max_retries,
                invoke=_invoke_instructor_attempt,
                should_retry=lambda exc: _check_retryable(exc, r),
                compute_delay=lambda attempt, exc: _compute_retry_delay(
                    attempt=attempt,
                    error=exc,
                    policy=r,
                    backoff_fn=backoff_fn,
                ),
                warning_sink=_warnings,
                logger=logger,
                on_error=(hooks.on_error if hooks and hooks.on_error else None),
                on_retry=r.on_retry,
                deadline_at=deadline_at,
                maybe_retry_hook=lambda exc, attempt, max_retries: _maybe_retry_with_openrouter_key_rotation(
                    error=exc,
                    attempt=attempt,
                    max_retries=max_retries,
                    current_model=current_model,
                    current_api_base=current_api_base,
                    user_kwargs=public_kwargs,
                    warning_sink=_warnings,
                    on_retry=r.on_retry,
                    caller="call_llm_structured",
                ),
            ))

        raise RuntimeError("call_llm_structured reached unexpected branch without return")

    try:
        return cast(tuple[T, LLMCallResult], run_sync_with_fallback(
            models=models,
            execute_model=_execute_model,
            should_fallback=lambda exc: not isinstance(
                exc, _StructuredFinalizationFailure
            ),
            on_fallback=on_fallback,
            warning_sink=_warnings,
            logger=logger,
            deadline_at=deadline_at,
        ))
    except Exception as e:
        terminal_error = _unwrap_structured_finalization_failure(e)
        _log_call_event(
            model=last_model_attempted,
            messages=messages,
            error=terminal_error,
            latency_s=time.monotonic() - _log_t0,
            caller="call_llm_structured",
            task=task,
            trace_id=trace_id,
            prompt_ref=prompt_ref,
            call_snapshot=call_snapshot,
            execution_path="error",
            retry_count=None,
        )
        raise wrap_error(terminal_error) from terminal_error

async def _acall_llm_structured_impl(
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[T],
    *,
    timeout: int = 60,
    logical_timeout: float | None = None,
    num_retries: int = 2,
    reasoning_effort: str | None = None,
    api_base: str | None = None,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: list[str] | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    cache: CachePolicy | AsyncCachePolicy | None = None,
    retry: RetryPolicy | None = None,
    fallback_models: list[str] | None = None,
    on_fallback: Callable[[str, Exception, str], None] | None = None,
    hooks: Hooks | None = None,
    config: ClientConfig | None = None,
    structured_output_policy: StructuredOutputPolicy | None = None,
    **kwargs: Any,
) -> tuple[T, LLMCallResult]:
    """Run the async structured-call runtime behind ``client.acall_llm_structured``."""
    reasoning_effort = (
        str(reasoning_effort).strip().lower()
        if reasoning_effort is not None
        else None
    )
    time = _client.time
    logger = _client.logger
    litellm = _client.litellm
    _rate_limit = _client._rate_limit
    _check_model_deprecation = _client._check_model_deprecation
    _normalize_prompt_ref = _client._normalize_prompt_ref
    _require_tags = _client._require_tags
    _normalize_timeout = _client._normalize_timeout
    _check_budget = _client._check_budget
    _resolve_call_plan = _client._resolve_call_plan
    _routing_policy_label = _client._routing_policy_label
    _is_agent_model = _client._is_agent_model
    _finalize_result = _client._finalize_result
    _build_routing_trace = _client._build_routing_trace
    _base_log_call_event = _client._log_call_event
    _effective_retry = _client._effective_retry
    _resolve_api_base_for_model = _client._resolve_api_base_for_model
    _background_mode_for_model = _client._background_mode_for_model
    _is_responses_api_model = _client._is_responses_api_model
    _cache_key = _client._cache_key
    _async_cache_get = _client._async_cache_get
    _async_cache_set = _client._async_cache_set
    exponential_backoff = _client.exponential_backoff
    _strict_json_schema = _client._strict_json_schema
    _strict_openai_response_model_schema = _client._strict_openai_response_model_schema
    _provider_compatible_discriminated_union_schema = (
        _client._provider_compatible_discriminated_union_schema
    )
    _openrouter_compatible_strict_json_schema = _client._openrouter_compatible_strict_json_schema
    _prepare_responses_kwargs = _client._prepare_responses_kwargs
    _extract_responses_usage = _client._extract_responses_usage
    _parse_cost_result = _client._parse_cost_result
    _compute_responses_cost = _client._compute_responses_cost
    _build_structured_call_result = _client._build_structured_call_result
    run_async_with_retry = _client.run_async_with_retry
    _check_retryable = _client._check_retryable
    _compute_retry_delay = _client._compute_retry_delay
    _maybe_retry_with_openrouter_key_rotation = _client._maybe_retry_with_openrouter_key_rotation
    _prepare_call_kwargs = _client._prepare_call_kwargs
    _first_choice_or_empty_error = _client._first_choice_or_empty_error
    _extract_usage = _client._extract_usage
    _compute_cost = _client._compute_cost
    _is_schema_error = _client._is_schema_error
    _NativeSchemaFallback = _client._NativeSchemaFallback
    run_async_with_fallback = _client.run_async_with_fallback
    wrap_error = _client.wrap_error

    _check_model_deprecation(model)
    output_policy = structured_output_policy or StructuredOutputPolicy()
    require_native_json_schema = output_policy.mode == "require_native_json_schema"
    cfg = config or ClientConfig.from_env()
    _log_t0 = time.monotonic()
    task = kwargs.pop("task", None)
    trace_id = kwargs.pop("trace_id", None)
    max_budget: float | None = kwargs.pop("max_budget", None)
    budget_scope_trace_id: str | None = kwargs.pop("budget_scope_trace_id", None)
    prompt_ref = _normalize_prompt_ref(kwargs.pop("prompt_ref", None))
    model_policy = str(kwargs.pop("model_policy", "enforce_allowlist"))
    model_justification = kwargs.pop("model_justification", None)
    task, trace_id, max_budget, _entry_warnings = _require_tags(
        task, trace_id, max_budget, caller="acall_llm_structured",
    )
    _logical_call_id = str(kwargs.pop("_lifecycle_logical_call_id", "")).strip() or uuid4().hex
    def _log_call_event(**event: Any) -> None:
        """Bind the returned result and terminal row to one attempt history."""
        result = event.get("result")
        if isinstance(result, LLMCallResult):
            result.logical_call_id = _logical_call_id
        _base_log_call_event(**event, logical_call_id=_logical_call_id)
        _io_log.record_call_lifecycle_event({"event_id": uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(), "logical_call_id": _logical_call_id, "trace_id": trace_id, "task": task, "phase": "completed" if isinstance(result, LLMCallResult) else "failed", "requested_model": model, "resolved_model": result.model if isinstance(result, LLMCallResult) else None, "call_kind": "structured", "error_type": type(event["error"]).__name__ if event.get("error") is not None else None})
    timeout = _normalize_timeout(
        timeout,
        caller="acall_llm_structured",
        warning_sink=_entry_warnings,
        logger=logger,
        log_policy_once_enabled=True,
    )
    logical_timeout = _normalize_logical_timeout(logical_timeout)
    deadline_at = _logical_deadline_at(logical_timeout)

    def _attempt_timeout() -> tuple[float, bool]:
        return _effective_attempt_timeout(timeout, deadline_at=deadline_at)

    _check_budget(
        trace_id,
        max_budget,
        budget_scope_trace_id=budget_scope_trace_id,
        warning_sink=_entry_warnings,
    )
    public_kwargs = _client._strip_llm_internal_kwargs(dict(kwargs))
    snapshot_public_kwargs = dict(public_kwargs)
    snapshot_public_kwargs["model_policy"] = model_policy
    if logical_timeout is not None:
        snapshot_public_kwargs["logical_timeout"] = logical_timeout
    if model_justification is not None:
        snapshot_public_kwargs["model_justification"] = model_justification
    _inject_langfuse_metadata(kwargs, task=task, trace_id=trace_id)
    r = _effective_retry(retry, num_retries, base_delay, max_delay, retry_on, on_retry)
    from llm_client.observability.replay import build_call_snapshot

    call_snapshot = build_call_snapshot(
        public_api="acall_llm_structured",
        call_kind="structured",
        requested_model=model,
        messages=messages,
        prompt_ref=prompt_ref,
        max_budget=max_budget,
        timeout=timeout,
        num_retries=num_retries,
        reasoning_effort=reasoning_effort,
        api_base=api_base,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_on=retry_on,
        fallback_models=fallback_models,
        public_kwargs=snapshot_public_kwargs,
        retry_policy=r,
        cache_policy=cache,
        structured_output_mode=output_policy.mode,
        response_model=response_model,
    )
    plan = _resolve_call_plan(
        model=model,
        fallback_models=fallback_models,
        api_base=api_base,
        config=cfg,
        model_policy=model_policy,
        model_justification=model_justification,
        reasoning_effort=reasoning_effort,
    )
    models = plan.models
    routing_policy = str(plan.routing_trace.get("routing_policy", _routing_policy_label(cfg)))
    model_policy_trace = plan.routing_trace.get("model_policy")
    if plan.primary_model.startswith("codex"):
        legacy_effort = public_kwargs.get("model_reasoning_effort")
        if (
            legacy_effort is not None
            and str(legacy_effort).strip().lower() != reasoning_effort
        ):
            raise LLMConfigurationError(
                "reasoning_effort conflicts with model_reasoning_effort for Codex"
            )
        public_kwargs["model_reasoning_effort"] = reasoning_effort

    if _is_agent_model(model):
        if require_native_json_schema:
            capability_error = LLMCapabilityError(
                f"Model {model} uses an Agent SDK structured path, not provider-native JSON schema."
            )
            _log_call_event(
                model=model,
                messages=messages,
                error=capability_error,
                latency_s=time.monotonic() - _log_t0,
                caller="acall_llm_structured",
                task=task,
                trace_id=trace_id,
                prompt_ref=prompt_ref,
                call_snapshot=call_snapshot,
                execution_path="error",
                retry_count=None,
            )
            raise capability_error
        from llm_client.sdk.agents import _route_acall_structured

        if hooks and hooks.before_call:
            hooks.before_call(model, messages, public_kwargs)
        attempt_timeout, logical_cap = _attempt_timeout()
        parsed, llm_result = await _run_async_with_deadline(
            lambda: _route_acall_structured(
                model,
                messages,
                response_model,
                # Preserve the precise remaining cap across the legacy integral
                # SDK annotation; runtime timeout consumers accept fractional values.
                timeout=cast(int, attempt_timeout),
                **public_kwargs,
            ),
            timeout=attempt_timeout,
            logical_cap=logical_cap,
        )
        llm_result = _finalize_result(
            llm_result,
            requested_model=model,
            resolved_model=llm_result.resolved_model,
            routing_trace=_build_routing_trace(
                requested_model=model,
                attempted_models=[plan.primary_model],
                selected_model=llm_result.resolved_model,
                requested_api_base=api_base,
                effective_api_base=api_base,
                routing_policy=routing_policy,
                model_policy=model_policy_trace,
            ),
        )
        if hooks and hooks.after_call:
            hooks.after_call(llm_result)
        _log_call_event(
            model=model,
            messages=messages,
            result=llm_result,
            latency_s=time.monotonic() - _log_t0,
            caller="acall_llm_structured",
            task=task,
            trace_id=trace_id,
            prompt_ref=prompt_ref,
            call_snapshot=call_snapshot,
            execution_path="agent_sdk",
            retry_count=0,
            response_format_type="agent_sdk",
        )
        return cast(T, parsed), llm_result
    _warnings: list[str] = list(_entry_warnings)
    _model_fqn = f"{response_model.__module__}.{response_model.__qualname__}"
    last_model_attempted = model
    next_structured_attempt_ordinal = 0
    structured_attempt_costs = _AttemptCostLedger()

    async def _execute_model(model_idx: int, current_model: str) -> tuple[T, LLMCallResult]:
        nonlocal last_model_attempted, next_structured_attempt_ordinal
        last_model_attempted = current_model
        current_api_base = _resolve_api_base_for_model(current_model, api_base, cfg)
        background_mode = _background_mode_for_model(
            model=current_model,
            use_responses=_is_responses_api_model(current_model),
            reasoning_effort=reasoning_effort,
        )
        key: str | None = None
        if cache is not None:
            key = _cache_key(
                current_model,
                messages,
                response_model=_model_fqn,
                reasoning_effort=reasoning_effort,
                **public_kwargs,
            )
            cached = await _async_cache_get(cache, key)
            if cached is not None:
                reparsed = response_model.model_validate_json(cached.content)
                cached_result = _finalize_result(
                    cached,
                    cache_hit=True,
                    requested_model=model,
                    resolved_model=current_model,
                    routing_trace=_build_routing_trace(
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        selected_model=current_model,
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    ),
                )
                _log_call_event(
                    model=current_model,
                    messages=messages,
                    result=cached_result,
                    latency_s=time.monotonic() - _log_t0,
                    caller="acall_llm_structured",
                    task=task,
                    trace_id=trace_id,
                    prompt_ref=prompt_ref,
                    call_snapshot=call_snapshot,
                    execution_path="responses_api",
                    retry_count=0,
                    response_format_type="json_schema",
                )
                return reparsed, cached_result

        if hooks and hooks.before_call:
            hooks.before_call(current_model, messages, public_kwargs)

        backoff_fn = r.backoff or exponential_backoff

        if _is_responses_api_model(current_model):
            _prepare_raw_artifact_store_for_runtime()
            schema = _provider_compatible_discriminated_union_schema(
                _strict_openai_response_model_schema(response_model)
            )
            if current_model.startswith("openrouter/"):
                schema = _openrouter_compatible_strict_json_schema(schema)
            _responses_schema_hash_async = _hashlib.sha256(
                _json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()[:16]
            resp_kwargs = _prepare_responses_kwargs(
                current_model,
                messages,
                timeout=timeout,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            resp_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": _provider_schema_name(response_model),
                    "schema": schema,
                    "strict": True,
                }
            }

            response_input = str(resp_kwargs["input"])
            pending_repair_message_async: dict[str, str] | None = None
            responses_recovery_pending_async: set[int] = set()
            responses_attempt_ordinals_async: dict[int, int] = {}

            def _responses_attempt_ordinal_async(local_attempt: int) -> int:
                """Assign one logical-call-global ordinal to an async Responses attempt."""

                nonlocal next_structured_attempt_ordinal
                if local_attempt not in responses_attempt_ordinals_async:
                    responses_attempt_ordinals_async[local_attempt] = (
                        next_structured_attempt_ordinal
                    )
                    next_structured_attempt_ordinal += 1
                return responses_attempt_ordinals_async[local_attempt]

            def _record_responses_recovery_async(
                attempt: int,
                _error: Exception,
                decision: Literal["retry", "exhausted"],
            ) -> None:
                """Persist the async retry kernel's Responses disposition once."""

                logical_attempt = _responses_attempt_ordinal_async(attempt)
                if logical_attempt not in responses_recovery_pending_async:
                    return
                responses_recovery_pending_async.remove(logical_attempt)
                recovery_decision: RecoveryDecision = decision
                if decision == "exhausted" and model_idx < len(models) - 1:
                    recovery_decision = "fallback"
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_responses_schema_hash_async,
                        event_type="recovery_decided",
                        execution_path="responses_api",
                        recovery_decision=recovery_decision,
                    )
                )

            async def _invoke_responses_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                nonlocal pending_repair_message_async
                logical_attempt = _responses_attempt_ordinal_async(attempt)
                structured_attempt_costs.mark_started(logical_attempt)
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_responses_schema_hash_async,
                        event_type="started",
                        execution_path="responses_api",
                    )
                )
                call_kwargs = dict(resp_kwargs)
                if pending_repair_message_async is not None:
                    call_kwargs["input"] = (
                        f"{response_input}\n\nUser: {pending_repair_message_async['content']}"
                    )
                    pending_repair_message_async = None
                    logger.info(
                        "acall_llm_structured: appended validation repair message for responses attempt %d",
                        attempt,
                    )

                attempt_received = False
                attempt_validated = False

                async def provider_call() -> Any:
                    async with _rate_limit.aacquire(current_model):
                        return await _await_with_safety_ceiling(
                            litellm.aresponses(**call_kwargs),
                            caller="acall_llm_structured.responses_api",
                            model=current_model,
                        )

                try:
                    attempt_timeout, logical_cap = _attempt_timeout()
                    call_kwargs["timeout"] = attempt_timeout
                    response = await _run_async_with_deadline(
                        provider_call,
                        timeout=attempt_timeout,
                        logical_cap=logical_cap,
                    )
                    raw_content = getattr(response, "output_text", None) or ""
                    if not raw_content.strip():
                        raise _EmptyStructuredContentError(
                            "Empty content from LLM (responses API structured)"
                        )
                    record_structured_attempt_event(
                        _received_attempt_event(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash_async,
                            raw_content=raw_content,
                            execution_path="responses_api",
                        )
                    )
                    attempt_received = True
                    usage = _extract_responses_usage(response)
                    attempt_cost, attempt_cost_source = _parse_cost_result(
                        _compute_responses_cost(response, usage),
                        default_source="computed",
                    )
                    structured_attempt_costs.record_response(
                        logical_attempt,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                    )
                    try:
                        parsed = _robust_validate_json(response_model, raw_content)
                    except ValidationError as validation_error:
                        record_structured_attempt_event(
                            _attempt_event(
                                logical_call_id=_logical_call_id,
                                trace_id=trace_id,
                                task=task,
                                attempt=logical_attempt,
                                model=current_model,
                                schema_hash=_responses_schema_hash_async,
                                event_type="validation_failed",
                                execution_path="responses_api",
                                validation_error=validation_error,
                            )
                        )
                        responses_recovery_pending_async.add(logical_attempt)
                        retry_exc = _StructuredValidationRetry(
                            raw_content, validation_error
                        )
                        pending_repair_message_async = (
                            _build_validation_repair_message(retry_exc)
                        )
                        raise retry_exc from validation_error
                    except Exception as parse_error:
                        _record_response_parse_failure(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash_async,
                            execution_path="responses_api",
                        )
                        responses_recovery_pending_async.add(logical_attempt)
                        raise _StructuredParseRetry(
                            "Provider response was not valid JSON."
                        ) from parse_error
                    attempt_validated = True
                    record_structured_attempt_event(
                        _attempt_event(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash_async,
                            event_type="validated",
                            execution_path="responses_api",
                        )
                    )

                    if attempt > 0:
                        logger.info(
                            "acall_llm_structured (responses) succeeded after %d retries",
                            attempt,
                        )

                    llm_result = _build_structured_call_result(
                        parsed=parsed,
                        usage=usage,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                        current_model=current_model,
                        finish_reason="stop",
                        raw_response=response,
                        warnings=_warnings,
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    )
                    structured_attempt_costs.apply(llm_result)
                    if hooks and hooks.after_call:
                        hooks.after_call(llm_result)
                    if cache is not None and key is not None:
                        await _async_cache_set(cache, key, llm_result)
                    _log_call_event(
                        model=current_model,
                        messages=messages,
                        result=llm_result,
                        latency_s=time.monotonic() - _log_t0,
                        caller="acall_llm_structured",
                        task=task,
                        trace_id=trace_id,
                        prompt_ref=prompt_ref,
                        call_snapshot=call_snapshot,
                        execution_path="responses_api",
                        retry_count=attempt,
                        schema_hash=_responses_schema_hash_async,
                        response_format_type="responses_api",
                    )
                    return parsed, llm_result
                except Exception as exc:
                    if attempt_validated:
                        raise _StructuredFinalizationFailure(exc) from exc
                    if isinstance(exc, StructuredRawArtifactError):
                        raise _StructuredFinalizationFailure(exc) from exc
                    if attempt_received and not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ):
                        raise _StructuredFinalizationFailure(exc) from exc
                    if not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ):
                        _record_execution_failure(
                            error=exc,
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_responses_schema_hash_async,
                            execution_path="responses_api",
                        )
                        responses_recovery_pending_async.add(logical_attempt)
                    _raise_if_unsupported_gpt5_structured_schema(
                        model=current_model,
                        error=exc,
                        caller="acall_llm_structured",
                    )
                    raise

            def _on_responses_error_async(exc: Exception, attempt: int) -> None:
                if hooks and hooks.on_error:
                    try:
                        hooks.on_error(
                            _unwrap_structured_finalization_failure(exc), attempt
                        )
                    except Exception as hook_error:
                        if isinstance(exc, _StructuredFinalizationFailure):
                            raise _StructuredFinalizationFailure(hook_error) from exc
                        raise

            return cast(tuple[T, LLMCallResult], await run_async_with_retry(
                caller="acall_llm_structured",
                model=current_model,
                max_retries=r.max_retries,
                invoke=_invoke_responses_attempt,
                should_retry=lambda exc: not isinstance(
                    exc, _StructuredFinalizationFailure
                )
                and (
                    isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    )
                    or _check_retryable(exc, r)
                ),
                compute_delay=lambda attempt, exc: _compute_retry_delay(
                    attempt=attempt,
                    error=exc,
                    policy=r,
                    backoff_fn=backoff_fn,
                ),
                warning_sink=_warnings,
                logger=logger,
                on_error=_on_responses_error_async,
                on_retry=r.on_retry,
                on_decision=_record_responses_recovery_async,
                deadline_at=deadline_at,
                maybe_retry_hook=lambda exc, attempt, max_retries: (
                    False
                    if isinstance(exc, _StructuredFinalizationFailure)
                    else _maybe_retry_with_openrouter_key_rotation(
                        error=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        current_model=current_model,
                        current_api_base=current_api_base,
                        user_kwargs=public_kwargs,
                        warning_sink=_warnings,
                        on_retry=r.on_retry,
                        caller="acall_llm_structured",
                    )
                ),
            ))

        supports_schema = _model_supports_native_schema(current_model)
        _native_schema_failed = False
        if require_native_json_schema and not supports_schema:
            raise LLMCapabilityError(
                f"Model {current_model} does not support native JSON schema; "
                "strict structured-output policy forbids Instructor fallback."
            )
        if supports_schema:
            _prepare_raw_artifact_store_for_runtime()
            schema = _native_provider_schema(response_model, model=current_model)
            base_kwargs = _prepare_call_kwargs(
                current_model,
                messages,
                timeout=timeout,
                num_retries=r.max_retries,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            _schema_hash_async = _hashlib.sha256(
                _json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()[:16]
            base_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _provider_schema_name(response_model),
                    "schema": schema,
                    "strict": True,
                },
            }

            _pending_repair_message_async: dict[str, str] | None = None
            _recovery_pending_async: set[int] = set()
            _attempt_ordinals_async: dict[int, int] = {}

            def _native_attempt_ordinal_async(local_attempt: int) -> int:
                """Assign one contiguous ordinal when an async attempt starts."""

                nonlocal next_structured_attempt_ordinal
                if local_attempt not in _attempt_ordinals_async:
                    _attempt_ordinals_async[local_attempt] = next_structured_attempt_ordinal
                    next_structured_attempt_ordinal += 1
                return _attempt_ordinals_async[local_attempt]

            def _record_native_recovery_async(
                attempt: int,
                error: Exception,
                decision: Literal["retry", "exhausted"],
            ) -> None:
                """Persist the async retry kernel's actual disposition exactly once."""

                logical_attempt = _native_attempt_ordinal_async(attempt)
                if logical_attempt not in _recovery_pending_async:
                    return
                _recovery_pending_async.remove(logical_attempt)
                recovery_decision: RecoveryDecision = decision
                if decision == "exhausted" and (
                    (isinstance(error, _NativeSchemaFallback) and not require_native_json_schema)
                    or model_idx < len(models) - 1
                ):
                    recovery_decision = "fallback"
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_schema_hash_async,
                        event_type="recovery_decided",
                        recovery_decision=recovery_decision,
                    )
                )

            async def _invoke_native_schema_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                nonlocal _pending_repair_message_async
                logical_attempt = _native_attempt_ordinal_async(attempt)
                structured_attempt_costs.mark_started(logical_attempt)
                record_structured_attempt_event(
                    _attempt_event(
                        logical_call_id=_logical_call_id,
                        trace_id=trace_id,
                        task=task,
                        attempt=logical_attempt,
                        model=current_model,
                        schema_hash=_schema_hash_async,
                        event_type="started",
                    )
                )
                if _pending_repair_message_async is not None:
                    base_kwargs["messages"] = list(base_kwargs["messages"]) + [_pending_repair_message_async]
                    _pending_repair_message_async = None
                    logger.info("acall_llm_structured: appended validation repair message for attempt %d", attempt)
                attempt_validated = False
                async def provider_call() -> Any:
                    async with _rate_limit.aacquire(current_model):
                        return await _await_with_safety_ceiling(
                            litellm.acompletion(**base_kwargs),
                            caller="acall_llm_structured.native_schema",
                            model=current_model,
                        )

                try:
                    attempt_timeout, logical_cap = _attempt_timeout()
                    base_kwargs["timeout"] = attempt_timeout
                    response = await _run_async_with_deadline(
                        provider_call,
                        timeout=attempt_timeout,
                        logical_cap=logical_cap,
                    )
                    first_choice = _first_choice_or_empty_error(
                        response,
                        model=current_model,
                        provider="litellm_completion_structured",
                    )
                    raw_content = first_choice.message.content or ""
                    if not raw_content.strip():
                        raise _EmptyStructuredContentError("Empty content from LLM (native JSON schema structured)")
                    record_structured_attempt_event(_received_attempt_event(
                        logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                        attempt=logical_attempt, model=current_model, schema_hash=_schema_hash_async,
                        raw_content=raw_content,
                    ))
                    attempt_cost, attempt_cost_source = _parse_cost_result(
                        _compute_cost(response)
                    )
                    structured_attempt_costs.record_response(
                        logical_attempt,
                        cost=attempt_cost,
                        cost_source=attempt_cost_source,
                    )
                    try:
                        parsed = _robust_validate_json(response_model, raw_content)
                    except ValidationError as ve:
                        record_structured_attempt_event(_attempt_event(
                            logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                            attempt=logical_attempt, model=current_model, schema_hash=_schema_hash_async,
                            event_type="validation_failed", validation_error=ve,
                        ))
                        _recovery_pending_async.add(logical_attempt)
                        retry_exc = _StructuredValidationRetry(raw_content, ve)
                        _pending_repair_message_async = _build_validation_repair_message(retry_exc)
                        raise retry_exc from ve
                    except Exception as parse_error:
                        _record_response_parse_failure(
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_schema_hash_async,
                        )
                        _recovery_pending_async.add(logical_attempt)
                        raise _StructuredParseRetry(
                            "Provider response was not valid JSON."
                        ) from parse_error
                    attempt_validated = True
                    record_structured_attempt_event(_attempt_event(
                        logical_call_id=_logical_call_id, trace_id=trace_id, task=task,
                        attempt=logical_attempt, model=current_model, schema_hash=_schema_hash_async,
                        event_type="validated",
                    ))
                    usage = _extract_usage(response)
                    cost, cost_source = attempt_cost, attempt_cost_source
                    finish_reason: str = first_choice.finish_reason or "stop"

                    if attempt > 0:
                        logger.info("acall_llm_structured (native schema) succeeded after %d retries", attempt)

                    llm_result = _build_structured_call_result(
                        parsed=parsed,
                        usage=usage,
                        cost=cost,
                        cost_source=cost_source,
                        current_model=current_model,
                        finish_reason=finish_reason,
                        raw_response=response,
                        warnings=_warnings,
                        requested_model=model,
                        attempted_models=models[:model_idx + 1],
                        requested_api_base=api_base,
                        effective_api_base=current_api_base,
                        background_mode=background_mode,
                        routing_policy=routing_policy,
                        model_policy=model_policy_trace,
                    )
                    structured_attempt_costs.apply(llm_result)
                    if hooks and hooks.after_call:
                        hooks.after_call(llm_result)
                    if cache is not None and key is not None:
                        await _async_cache_set(cache, key, llm_result)
                    _log_call_event(
                        model=current_model,
                        messages=messages,
                        result=llm_result,
                        latency_s=time.monotonic() - _log_t0,
                        caller="acall_llm_structured",
                        task=task,
                        trace_id=trace_id,
                        prompt_ref=prompt_ref,
                        call_snapshot=call_snapshot,
                        execution_path="native_schema",
                        retry_count=attempt,
                        schema_hash=_schema_hash_async,
                        response_format_type="json_schema",
                    )
                    _record_openrouter_native_route_observation(
                        result=llm_result,
                        provider_schema=schema,
                        response_model=response_model,
                    )
                    return parsed, llm_result
                except Exception as exc:
                    if attempt_validated:
                        raise _StructuredFinalizationFailure(exc) from exc
                    if isinstance(exc, StructuredRawArtifactError):
                        raise _StructuredFinalizationFailure(exc) from exc
                    try:
                        provider_validation = _record_provider_schema_validation_failure(
                            error=exc, logical_call_id=_logical_call_id,
                            trace_id=trace_id, task=task, attempt=logical_attempt,
                            model=current_model, schema_hash=_schema_hash_async,
                        )
                    except StructuredRawArtifactError as artifact_error:
                        raise _StructuredFinalizationFailure(artifact_error) from artifact_error
                    if provider_validation:
                        _recovery_pending_async.add(logical_attempt)
                    elif not isinstance(
                        exc, (_StructuredValidationRetry, _StructuredParseRetry)
                    ) and not attempt_validated:
                        _record_execution_failure(
                            error=exc,
                            logical_call_id=_logical_call_id,
                            trace_id=trace_id,
                            task=task,
                            attempt=logical_attempt,
                            model=current_model,
                            schema_hash=_schema_hash_async,
                        )
                        _recovery_pending_async.add(logical_attempt)
                    _raise_if_unsupported_gpt5_structured_schema(
                        model=current_model,
                        error=exc,
                        caller="acall_llm_structured",
                    )
                    if _is_schema_error(exc):
                        raise _NativeSchemaFallback(str(exc)) from exc
                    raise

            def _on_native_schema_error(exc: Exception, attempt: int) -> None:
                if isinstance(exc, _NativeSchemaFallback):
                    return
                if hooks and hooks.on_error:
                    try:
                        hooks.on_error(_unwrap_structured_finalization_failure(exc), attempt)
                    except Exception as hook_error:
                        if isinstance(exc, _StructuredFinalizationFailure):
                            raise _StructuredFinalizationFailure(hook_error) from exc
                        raise

            try:
                return cast(tuple[T, LLMCallResult], await run_async_with_retry(
                    caller="acall_llm_structured",
                    model=current_model,
                    max_retries=r.max_retries,
                    invoke=_invoke_native_schema_attempt,
                    should_retry=lambda exc: not isinstance(exc, _StructuredFinalizationFailure)
                    and (
                        isinstance(
                            exc, (_StructuredValidationRetry, _StructuredParseRetry)
                        )
                        or (not isinstance(exc, _NativeSchemaFallback) and _check_retryable(exc, r))
                    ),
                    compute_delay=lambda attempt, exc: _compute_retry_delay(
                        attempt=attempt,
                        error=exc,
                        policy=r,
                        backoff_fn=backoff_fn,
                    ),
                    warning_sink=_warnings,
                    logger=logger,
                    on_error=_on_native_schema_error,
                    on_retry=r.on_retry,
                    on_decision=_record_native_recovery_async,
                    deadline_at=deadline_at,
                    maybe_retry_hook=lambda exc, attempt, max_retries: (
                        False if isinstance(exc, (_NativeSchemaFallback, _StructuredFinalizationFailure)) else _maybe_retry_with_openrouter_key_rotation(
                            error=exc,
                            attempt=attempt,
                            max_retries=max_retries,
                            current_model=current_model,
                            current_api_base=current_api_base,
                            user_kwargs=public_kwargs,
                            warning_sink=_warnings,
                            on_retry=r.on_retry,
                            caller="acall_llm_structured",
                        )
                    ),
                ))
            except _NativeSchemaFallback as schema_error:
                if require_native_json_schema:
                    raise LLMCapabilityError(
                        f"Provider rejected native JSON schema for model {current_model}; "
                        "strict structured-output policy forbids Instructor fallback.",
                        original=schema_error,
                    ) from schema_error
                logger.warning(
                    "Native JSON schema rejected by provider (%s), falling back to instructor: %s",
                    current_model,
                    schema_error,
                )
                _native_schema_failed = True

        if not supports_schema or _native_schema_failed:
            client = _instructor_from_litellm(litellm.acompletion)
            base_kwargs = _prepare_call_kwargs(
                current_model,
                messages,
                timeout=timeout,
                num_retries=r.max_retries,
                reasoning_effort=reasoning_effort,
                api_base=current_api_base,
                kwargs=public_kwargs,
                warning_sink=_warnings,
            )
            call_kwargs = {**base_kwargs, "response_model": response_model, "max_retries": 2}
            _instructor_schema_hash_async = _hashlib.sha256(
                _json.dumps(response_model.model_json_schema(), sort_keys=True).encode()
            ).hexdigest()[:16]

            async def _invoke_instructor_attempt(attempt: int) -> tuple[T, LLMCallResult]:
                async def instructor_call() -> Any:
                    return await _await_with_safety_ceiling(
                        client.chat.completions.create_with_completion(**call_kwargs),
                        caller="acall_llm_structured.instructor",
                        model=current_model,
                    )

                attempt_timeout, logical_cap = _attempt_timeout()
                call_kwargs["timeout"] = attempt_timeout
                parsed, completion_response = await _run_async_with_deadline(
                    instructor_call,
                    timeout=attempt_timeout,
                    logical_cap=logical_cap,
                )

                usage = _extract_usage(completion_response)
                cost, cost_source = _parse_cost_result(_compute_cost(completion_response))
                completion_choice = _first_choice_or_empty_error(
                    completion_response,
                    model=current_model,
                    provider="instructor_completion_structured",
                )
                finish_reason = completion_choice.finish_reason or ""

                if attempt > 0:
                    logger.info("acall_llm_structured succeeded after %d retries", attempt)

                llm_result = _build_structured_call_result(
                    parsed=parsed,
                    usage=usage,
                    cost=cost,
                    cost_source=cost_source,
                    current_model=current_model,
                    finish_reason=finish_reason,
                    raw_response=completion_response,
                    warnings=_warnings,
                    requested_model=model,
                    attempted_models=models[:model_idx + 1],
                    requested_api_base=api_base,
                    effective_api_base=current_api_base,
                    background_mode=background_mode,
                    routing_policy=routing_policy,
                    model_policy=model_policy_trace,
                )

                if hooks and hooks.after_call:
                    hooks.after_call(llm_result)
                if cache is not None and key is not None:
                    await _async_cache_set(cache, key, llm_result)
                _log_call_event(
                    model=current_model,
                    messages=messages,
                    result=llm_result,
                    latency_s=time.monotonic() - _log_t0,
                    caller="acall_llm_structured",
                    task=task,
                    trace_id=trace_id,
                    prompt_ref=prompt_ref,
                    call_snapshot=call_snapshot,
                    execution_path="instructor",
                    retry_count=attempt,
                    schema_hash=_instructor_schema_hash_async,
                    response_format_type="instructor",
                )
                return parsed, llm_result

            return cast(tuple[T, LLMCallResult], await run_async_with_retry(
                caller="acall_llm_structured",
                model=current_model,
                max_retries=r.max_retries,
                invoke=_invoke_instructor_attempt,
                should_retry=lambda exc: _check_retryable(exc, r),
                compute_delay=lambda attempt, exc: _compute_retry_delay(
                    attempt=attempt,
                    error=exc,
                    policy=r,
                    backoff_fn=backoff_fn,
                ),
                warning_sink=_warnings,
                logger=logger,
                on_error=(hooks.on_error if hooks and hooks.on_error else None),
                on_retry=r.on_retry,
                deadline_at=deadline_at,
                maybe_retry_hook=lambda exc, attempt, max_retries: _maybe_retry_with_openrouter_key_rotation(
                    error=exc,
                    attempt=attempt,
                    max_retries=max_retries,
                    current_model=current_model,
                    current_api_base=current_api_base,
                    user_kwargs=public_kwargs,
                    warning_sink=_warnings,
                    on_retry=r.on_retry,
                    caller="acall_llm_structured",
                ),
            ))

        raise RuntimeError("acall_llm_structured reached unexpected branch without return")

    try:
        return cast(tuple[T, LLMCallResult], await run_async_with_fallback(
            models=models,
            execute_model=_execute_model,
            should_fallback=lambda exc: not isinstance(
                exc, _StructuredFinalizationFailure
            ),
            on_fallback=on_fallback,
            warning_sink=_warnings,
            logger=logger,
            deadline_at=deadline_at,
        ))
    except Exception as e:
        terminal_error = _unwrap_structured_finalization_failure(e)
        # Unwrap InstructorRetryException to expose the underlying provider error
        # in the observability record (e.g. BadRequestError, RateLimitError).
        log_error = _unwrap_instructor_retry(terminal_error)
        _log_call_event(
            model=last_model_attempted,
            messages=messages,
            error=log_error,
            latency_s=time.monotonic() - _log_t0,
            caller="acall_llm_structured",
            task=task,
            trace_id=trace_id,
            prompt_ref=prompt_ref,
            call_snapshot=call_snapshot,
            execution_path="error",
            retry_count=None,
        )
        raise wrap_error(terminal_error) from terminal_error
