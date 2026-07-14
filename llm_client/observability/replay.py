"""Shared call snapshot, comparison, and replay helpers.

This module captures one durable truth for cross-project observability work:
the normalized call contract at the `llm_client` boundary. That call snapshot
is used for three related jobs:

1. stable request fingerprinting,
2. compact divergence reports between two captured calls,
3. controlled replay of a captured call through the shared runtime.

The goal is not to reconstruct arbitrary project workflow state. The goal is to
make call-level debugging reusable across projects once a workflow has already
reached the shared `llm_client` boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Mapping, Self

import llm_client.io_log as _io_log
from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client.execution.retry import RetryPolicy

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]

_SNAPSHOT_VERSION = 3
_OBSERVABILITY_ONLY_KWARGS = {
    "task",
    "trace_id",
    "max_budget",
    "prompt_ref",
    "lifecycle_heartbeat_interval_s",
    "lifecycle_stall_after_s",
}
_REPLAY_RESERVED_PUBLIC_KWARGS = {
    "api_base",
    "base_delay",
    "cache",
    "config",
    "execution_mode",
    "fallback_models",
    "hooks",
    "max_budget",
    "max_delay",
    "messages",
    "model",
    "num_retries",
    "on_fallback",
    "on_retry",
    "parent_trace_id",
    "prompt_ref",
    "reasoning_effort",
    "response_model",
    "retry",
    "retry_on",
    "structured_output_policy",
    "task",
    "timeout",
    "trace_id",
}
_REPLAY_PUBLIC_API_CALL_KINDS = {
    "call_llm": "text",
    "acall_llm": "text",
    "call_llm_structured": "structured",
    "acall_llm_structured": "structured",
}
_UNSUPPORTED_VALUE_MARKER = "__llm_client_replay_unsupported__"
_LEGACY_DIAGNOSTIC_KEYS = frozenset({"__type__", "__repr__"})


class _ReplayRetryPolicyV2(BaseModel):
    """Replay-safe subset of the effective typed retry policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_retries: int = Field(ge=0)
    base_delay: float = Field(ge=0)
    max_delay: float = Field(ge=0)
    retry_on: list[str] | None
    on_retry: None
    backoff: None
    should_retry: None


class _ReplayCachePolicyV2(BaseModel):
    """Only disabled cache state is reconstructable without a cache registry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    mode: Literal["disabled"]


class _ReplayExecutionPolicyV2(BaseModel):
    """Typed effective execution controls required for exact v2 replay."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    timeout: int = Field(ge=0)
    num_retries: int = Field(ge=0)
    reasoning_effort: str | None
    api_base: str | None
    base_delay: float = Field(ge=0)
    max_delay: float = Field(ge=0)
    retry_on: list[str] | None
    fallback_models: list[str] | None
    execution_mode: Literal["text", "structured", "workspace_agent", "workspace_tools"] | None
    structured_output_mode: Literal["auto", "require_native_json_schema"] | None
    retry_policy: _ReplayRetryPolicyV2
    cache_policy: _ReplayCachePolicyV2

    @model_validator(mode="after")
    def require_consistent_retry_projection(self) -> Self:
        """Reject drift between compatibility fields and typed retry authority."""

        retry = self.retry_policy
        if self.num_retries != retry.max_retries:
            raise ValueError("num_retries disagrees with retry_policy.max_retries")
        if self.base_delay != retry.base_delay:
            raise ValueError("base_delay disagrees with retry_policy.base_delay")
        if self.max_delay != retry.max_delay:
            raise ValueError("max_delay disagrees with retry_policy.max_delay")
        if self.retry_on != retry.retry_on:
            raise ValueError("retry_on disagrees with retry_policy.retry_on")
        return self


class _ReplayMetadataV2(BaseModel):
    """Typed replay support declaration stored beside every v2 request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    unsupported_keys: list[str]


class _ReplayRequestV2(BaseModel):
    """Closed replay request envelope for snapshot version 2."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requested_model: str
    messages: list[dict[str, Any]]
    prompt_ref: str | None
    control: _ReplayExecutionPolicyV2
    kwargs: dict[str, Any]
    response_model_fqn: str | None
    response_model_schema: dict[str, Any] | None


class _ReplaySnapshotV2(BaseModel):
    """Closed versioned envelope whose fields determine exact replay dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    snapshot_version: Literal[2]
    public_api: Literal[
        "call_llm",
        "acall_llm",
        "call_llm_structured",
        "acall_llm_structured",
    ]
    call_kind: Literal["text", "structured"]
    request: _ReplayRequestV2
    replay: _ReplayMetadataV2


class _ReplayExecutionPolicyV3(_ReplayExecutionPolicyV2):
    """V3 execution controls including the checked original-call spend ceiling."""

    max_budget: float = Field(ge=0, allow_inf_nan=False)


class _ReplayRequestV3(BaseModel):
    """Closed replay request envelope for snapshot version 3."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requested_model: str
    messages: list[dict[str, Any]]
    prompt_ref: str | None
    control: _ReplayExecutionPolicyV3
    kwargs: dict[str, Any]
    response_model_fqn: str | None
    response_model_schema: dict[str, Any] | None


class _ReplaySnapshotV3(BaseModel):
    """Closed envelope adding budget-complete original-call identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    snapshot_version: Literal[3]
    public_api: Literal[
        "call_llm",
        "acall_llm",
        "call_llm_structured",
        "acall_llm_structured",
    ]
    call_kind: Literal["text", "structured"]
    request: _ReplayRequestV3
    replay: _ReplayMetadataV2


def _qualified_name(value: type[Any]) -> str:
    """Return a stable fully qualified name for one class-like object."""

    return f"{value.__module__}.{value.__qualname__}"


def _callable_name(value: Any) -> str:
    """Return a stable diagnostic identity for an unsupported callable."""

    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return _qualified_name(type(value))


def _unsupported_value(value: Any, *, reason: str) -> JSONObject:
    """Return an intrinsic diagnostic that can never be mistaken for replay input."""

    return {
        _UNSUPPORTED_VALUE_MARKER: {
            "type": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
            "reason": reason,
            "repr": repr(value),
        }
    }


def _is_unsupported_diagnostic(value: Mapping[Any, Any]) -> bool:
    """Recognize current and historical diagnostics embedded in a snapshot."""

    marker = value.get(_UNSUPPORTED_VALUE_MARKER)
    if isinstance(marker, Mapping) and all(
        isinstance(marker.get(key), str) for key in ("type", "reason", "repr")
    ):
        return True
    return (
        frozenset(value.keys()) == _LEGACY_DIAGNOSTIC_KEYS
        and isinstance(value.get("__type__"), str)
        and isinstance(value.get("__repr__"), str)
    )


def _find_unsupported_diagnostic_paths(value: Any, *, path: str) -> list[str]:
    """Find intrinsic replay-unsupported diagnostics without trusting metadata."""

    if isinstance(value, Mapping):
        if _is_unsupported_diagnostic(value):
            return [path]
        paths: list[str] = []
        for key, child in value.items():
            paths.extend(
                _find_unsupported_diagnostic_paths(
                    child,
                    path=f"{path}.{key}",
                )
            )
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(
                _find_unsupported_diagnostic_paths(
                    child,
                    path=f"{path}[{index}]",
                )
            )
        return paths
    return []


def _normalize_json_value(value: Any) -> tuple[JSONValue, bool]:
    """Normalize arbitrary runtime values into JSON-like storage.

    The boolean indicates whether persistence preserves both value and Python type
    at the public-call boundary. Only recursively JSON-native values are replay-safe.
    Every lossy coercion becomes an intrinsic diagnostic so missing or false support
    metadata cannot make the substituted value dispatchable.
    """

    if value is None or type(value) in {str, int, bool}:
        return value, True
    if type(value) is float:
        if math.isfinite(value):
            return value, True
        return _unsupported_value(value, reason="non-finite float"), False
    if isinstance(value, Path):
        return _unsupported_value(value, reason="Path would become str"), False
    if type(value) is dict:
        if _is_unsupported_diagnostic(value):
            return dict(value), False
        normalized: JSONObject = {}
        supported = True
        for key in value:
            if type(key) is not str:
                return (
                    _unsupported_value(
                        value,
                        reason="mapping key would become str",
                    ),
                    False,
                )
        for key in sorted(value.keys()):
            child, child_supported = _normalize_json_value(value[key])
            normalized[key] = child
            supported = supported and child_supported
        return normalized, supported
    if isinstance(value, Mapping):
        return (
            _unsupported_value(
                value,
                reason="Mapping implementation would become dict",
            ),
            False,
        )
    if type(value) is list:
        normalized_items: list[JSONValue] = []
        supported = True
        for item in value:
            child, child_supported = _normalize_json_value(item)
            normalized_items.append(child)
            supported = supported and child_supported
        return normalized_items, supported
    if isinstance(value, tuple):
        return _unsupported_value(value, reason="tuple would become list"), False
    if isinstance(value, set):
        return _unsupported_value(value, reason="set would become list"), False
    if isinstance(value, list):
        return _unsupported_value(value, reason="list subclass would become list"), False
    if isinstance(value, type):
        return _unsupported_value(value, reason="type would become qualified name"), False

    return _unsupported_value(value, reason="value is not JSON-native"), False


def _normalize_messages(messages: list[dict[str, Any]]) -> tuple[list[JSONValue], bool]:
    """Normalize messages and report whether replay preserves their exact values."""

    normalized, supported = _normalize_json_value(messages)
    if isinstance(normalized, list):
        return normalized, supported
    raise TypeError("normalized messages must be a list")


def _normalize_public_kwargs(public_kwargs: Mapping[str, Any]) -> tuple[JSONObject, list[str]]:
    """Normalize replay kwargs and collect keys that cannot be replayed exactly."""

    normalized_kwargs: JSONObject = {}
    unsupported_keys: list[str] = []
    for key in sorted(public_kwargs.keys()):
        if key in _OBSERVABILITY_ONLY_KWARGS:
            continue
        value = public_kwargs[key]
        normalized_value, supported = _normalize_json_value(value)
        normalized_kwargs[key] = normalized_value
        if not supported:
            unsupported_keys.append(key)
    return normalized_kwargs, unsupported_keys


def _normalize_response_model_schema(response_model: type[Any] | None) -> JSONValue:
    """Return the full structured-output schema when a Pydantic model is supplied."""

    if response_model is None or not hasattr(response_model, "model_json_schema"):
        return None
    schema = response_model.model_json_schema()
    normalized, _ = _normalize_json_value(schema)
    return normalized


def _normalize_retry_policy(policy: RetryPolicy) -> tuple[JSONObject, list[str]]:
    """Serialize effective retry state and name fields replay cannot reconstruct."""

    unsupported: list[str] = []
    callable_fields: JSONObject = {}
    for field_name in ("on_retry", "backoff", "should_retry"):
        value = getattr(policy, field_name)
        if value is None:
            callable_fields[field_name] = None
            continue
        callable_fields[field_name] = _callable_name(value)
        unsupported.append(f"retry_policy.{field_name}")
    payload: JSONObject = {
        "max_retries": policy.max_retries,
        "base_delay": policy.base_delay,
        "max_delay": policy.max_delay,
        "retry_on": list(policy.retry_on) if policy.retry_on is not None else None,
        **callable_fields,
    }
    return payload, unsupported


def _normalize_cache_policy(policy: Any | None) -> tuple[JSONObject, list[str]]:
    """Serialize disabled cache exactly; mark arbitrary enabled caches unsupported."""

    if policy is None:
        return {"mode": "disabled"}, []
    return {
        "mode": "enabled",
        "type": _qualified_name(type(policy)),
    }, ["cache_policy"]


def build_call_snapshot(
    *,
    public_api: str,
    call_kind: str,
    requested_model: str,
    messages: list[dict[str, Any]],
    prompt_ref: str | None,
    max_budget: float,
    timeout: int,
    num_retries: int,
    reasoning_effort: str | None,
    api_base: str | None,
    base_delay: float,
    max_delay: float,
    retry_on: list[str] | None,
    fallback_models: list[str] | None,
    public_kwargs: Mapping[str, Any],
    retry_policy: RetryPolicy | None = None,
    cache_policy: Any | None = None,
    execution_mode: str | None = None,
    structured_output_mode: str | None = None,
    response_model: type[Any] | None = None,
) -> JSONObject:
    """Build the normalized call snapshot used for fingerprinting and replay.

    This captures caller-visible inputs at the `llm_client` boundary and keeps
    observability-only metadata out of the replay identity.
    """

    effective_retry = retry_policy or RetryPolicy(
        max_retries=num_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_on=retry_on,
    )
    retry_payload, retry_unsupported = _normalize_retry_policy(effective_retry)
    cache_payload, cache_unsupported = _normalize_cache_policy(cache_policy)
    normalized_kwargs, kwargs_unsupported = _normalize_public_kwargs(public_kwargs)
    normalized_messages, messages_supported = _normalize_messages(messages)
    message_unsupported = [] if messages_supported else ["messages"]
    unsupported_keys = sorted(
        set(
            kwargs_unsupported
            + retry_unsupported
            + cache_unsupported
            + message_unsupported
        )
    )
    response_model_fqn = _qualified_name(response_model) if response_model is not None else None
    snapshot: JSONObject = {
        "snapshot_version": _SNAPSHOT_VERSION,
        "public_api": public_api,
        "call_kind": call_kind,
        "request": {
            "requested_model": requested_model,
            "messages": normalized_messages,
            "prompt_ref": prompt_ref,
            "control": {
                "timeout": timeout,
                "max_budget": max_budget,
                "num_retries": effective_retry.max_retries,
                "reasoning_effort": reasoning_effort,
                "api_base": api_base,
                "base_delay": effective_retry.base_delay,
                "max_delay": effective_retry.max_delay,
                "retry_on": (
                    list(effective_retry.retry_on)
                    if effective_retry.retry_on is not None
                    else None
                ),
                "fallback_models": list(fallback_models) if fallback_models is not None else None,
                "execution_mode": execution_mode,
                "structured_output_mode": structured_output_mode,
                "retry_policy": retry_payload,
                "cache_policy": cache_payload,
            },
            "kwargs": normalized_kwargs,
            "response_model_fqn": response_model_fqn,
            "response_model_schema": _normalize_response_model_schema(response_model),
        },
        "replay": {
            "unsupported_keys": unsupported_keys,
        },
    }
    if (
        isinstance(max_budget, bool)
        or not isinstance(max_budget, (int, float))
        or not math.isfinite(max_budget)
        or max_budget < 0
    ):
        raise ValueError("invalid v3 call snapshot: max_budget must be finite and nonnegative")
    if unsupported_keys:
        return snapshot
    try:
        validated = _ReplaySnapshotV3.model_validate(snapshot)
    except Exception as error:
        raise ValueError(f"invalid v3 call snapshot: {error}") from error
    return validated.model_dump(mode="json")


def snapshot_request_identity(snapshot: Mapping[str, Any]) -> JSONObject:
    """Return the canonical request identity used for fingerprinting."""

    request = snapshot.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("snapshot is missing request identity")
    normalized_request, _ = _normalize_json_value(dict(request))
    if not isinstance(normalized_request, dict):
        raise TypeError("normalized request identity must be an object")
    return normalized_request


def snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    """Return a deterministic fingerprint for one normalized call snapshot."""

    request = snapshot_request_identity(snapshot)
    snapshot_version = snapshot.get("snapshot_version")
    if snapshot_version in {2, 3}:
        fingerprint_identity: JSONValue = {
            "snapshot_version": snapshot_version,
            "public_api": snapshot.get("public_api"),
            "call_kind": snapshot.get("call_kind"),
            "request": request,
            "replay": snapshot.get("replay"),
        }
    else:
        fingerprint_identity = request
    payload = json.dumps(
        fingerprint_identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview_value(value: Any, *, limit: int = 120) -> str:
    """Return a compact human-readable preview for diff output."""

    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=True)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...({len(text)} chars)"


def _diff_json_values(left: Any, right: Any, *, path: str) -> list[str]:
    """Return deterministic compact diffs between two JSON-like values."""

    if left == right:
        return []
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        diffs: list[str] = []
        keys = sorted(set(left.keys()) | set(right.keys()), key=str)
        for key in keys:
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                diffs.append(f"{child_path}: missing on left; right={_preview_value(right[key])}")
                continue
            if key not in right:
                diffs.append(f"{child_path}: left={_preview_value(left[key])}; missing on right")
                continue
            diffs.extend(_diff_json_values(left[key], right[key], path=child_path))
        return diffs
    if isinstance(left, list) and isinstance(right, list):
        diffs: list[str] = []
        max_len = max(len(left), len(right))
        for idx in range(max_len):
            child_path = f"{path}[{idx}]"
            if idx >= len(left):
                diffs.append(f"{child_path}: missing on left; right={_preview_value(right[idx])}")
                continue
            if idx >= len(right):
                diffs.append(f"{child_path}: left={_preview_value(left[idx])}; missing on right")
                continue
            diffs.extend(_diff_json_values(left[idx], right[idx], path=child_path))
        return diffs
    return [f"{path}: left={_preview_value(left)} right={_preview_value(right)}"]


def _decode_json_column(value: str | None) -> JSONValue:
    """Decode one JSON text column if present."""

    if value is None:
        return None
    loaded = json.loads(value)
    normalized, _ = _normalize_json_value(loaded)
    return normalized


def get_call_record(call_id: int) -> dict[str, Any]:
    """Return one persisted call record with decoded snapshot and messages."""

    db = _io_log._get_db()
    row = db.execute(
        """
        SELECT id, timestamp, project, model, messages, response,
               finish_reason, latency_s, error, caller, task, trace_id,
               prompt_ref, call_fingerprint, call_snapshot
        FROM llm_calls
        WHERE id = ?
        """,
        (call_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Call id {call_id} not found.")
    return {
        "id": row[0],
        "timestamp": row[1],
        "project": row[2],
        "model": row[3],
        "messages": _decode_json_column(row[4]),
        "response": row[5],
        "finish_reason": row[6],
        "latency_s": row[7],
        "error": row[8],
        "caller": row[9],
        "task": row[10],
        "trace_id": row[11],
        "prompt_ref": row[12],
        "call_fingerprint": row[13],
        "call_snapshot": _decode_json_column(row[14]),
    }


def get_call_snapshot(call_id: int) -> JSONObject:
    """Return the decoded call snapshot for one call id."""

    snapshot = get_call_record(call_id)["call_snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError(f"Call id {call_id} does not have a replayable call snapshot.")
    return snapshot


def compare_call_snapshots(left_call_id: int, right_call_id: int) -> dict[str, Any]:
    """Compare two captured calls and return a compact divergence report."""

    left = get_call_record(left_call_id)
    right = get_call_record(right_call_id)
    left_snapshot = left["call_snapshot"]
    right_snapshot = right["call_snapshot"]
    if not isinstance(left_snapshot, dict):
        raise ValueError(f"Call id {left_call_id} does not have a replayable call snapshot.")
    if not isinstance(right_snapshot, dict):
        raise ValueError(f"Call id {right_call_id} does not have a replayable call snapshot.")

    left_request = snapshot_request_identity(left_snapshot)
    right_request = snapshot_request_identity(right_snapshot)
    report = {
        "left_call_id": left_call_id,
        "right_call_id": right_call_id,
        "left_fingerprint": left["call_fingerprint"] or snapshot_fingerprint(left_snapshot),
        "right_fingerprint": right["call_fingerprint"] or snapshot_fingerprint(right_snapshot),
        "fingerprints_match": (left["call_fingerprint"] or snapshot_fingerprint(left_snapshot))
        == (right["call_fingerprint"] or snapshot_fingerprint(right_snapshot)),
        "request_differences": _diff_json_values(left_request, right_request, path="request"),
        "result_differences": _diff_json_values(
            {
                "model": left["model"],
                "finish_reason": left["finish_reason"],
                "error": left["error"],
                "response": left["response"],
            },
            {
                "model": right["model"],
                "finish_reason": right["finish_reason"],
                "error": right["error"],
                "response": right["response"],
            },
            path="result",
        ),
        "left_summary": {
            "project": left["project"],
            "caller": left["caller"],
            "task": left["task"],
            "trace_id": left["trace_id"],
            "model": left["model"],
            "error": left["error"],
        },
        "right_summary": {
            "project": right["project"],
            "caller": right["caller"],
            "task": right["task"],
            "trace_id": right["trace_id"],
            "model": right["model"],
            "error": right["error"],
        },
    }
    return report


def format_call_diff(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable divergence report."""

    left_call_id = report["left_call_id"]
    right_call_id = report["right_call_id"]
    header = [
        f"compare {left_call_id} vs {right_call_id}",
        f"fingerprints_match={report['fingerprints_match']}",
    ]
    request_diffs = list(report.get("request_differences", []))
    result_diffs = list(report.get("result_differences", []))
    lines = header
    lines.append("request:")
    lines.extend(
        [f"  - {diff}" for diff in request_diffs] if request_diffs else ["  - no request differences"]
    )
    lines.append("result:")
    lines.extend(
        [f"  - {diff}" for diff in result_diffs] if result_diffs else ["  - no result differences"]
    )
    return "\n".join(lines)


def _resolve_response_model(model_fqn: str) -> type[Any]:
    """Import and return a structured response model from its fully qualified name."""

    module_name, _, qualname = model_fqn.rpartition(".")
    if not module_name or not qualname:
        raise ValueError(f"Invalid response model path: {model_fqn!r}")
    module = importlib.import_module(module_name)
    current: Any = module
    for part in qualname.split("."):
        current = getattr(current, part)
    if not isinstance(current, type):
        raise TypeError(f"Resolved response model is not a type: {model_fqn!r}")
    return current


def _resolve_response_model_for_replay(
    request: Mapping[str, Any],
    *,
    call_id: int,
    snapshot_version: int,
) -> type[Any]:
    """Resolve a structured model and reject closed-envelope schema drift."""

    model_fqn = request.get("response_model_fqn")
    if not isinstance(model_fqn, str) or not model_fqn:
        raise ValueError(f"Call id {call_id} snapshot is missing request.response_model_fqn.")
    response_model = _resolve_response_model(model_fqn)
    if snapshot_version in {2, 3}:
        stored_schema = request.get("response_model_schema")
        current_schema = _normalize_response_model_schema(response_model)
        if stored_schema != current_schema:
            raise ValueError(
                f"Call id {call_id} response model schema no longer matches the captured snapshot."
            )
    return response_model


def _call_text_for_replay(
    model: str,
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> Any:
    """Dispatch one text replay through the shared public runtime."""

    from llm_client import call_llm

    return call_llm(model, messages, **kwargs)


def _call_structured_for_replay(
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[Any],
    **kwargs: Any,
) -> Any:
    """Dispatch one structured replay through the shared public runtime."""

    from llm_client import call_llm_structured

    return call_llm_structured(model, messages, response_model, **kwargs)


async def _acall_text_for_replay(
    model: str,
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> Any:
    """Dispatch one async text replay through the shared public runtime."""

    from llm_client import acall_llm

    return await acall_llm(model, messages, **kwargs)


async def _acall_structured_for_replay(
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[Any],
    **kwargs: Any,
) -> Any:
    """Dispatch one async structured replay through the shared public runtime."""

    from llm_client import acall_llm_structured

    return await acall_llm_structured(model, messages, response_model, **kwargs)


@contextmanager
def _temporary_project_override(project: str | None) -> Any:
    """Temporarily override the active observability project for one replay."""

    if project is None:
        yield
        return
    old_project = _io_log._project
    try:
        _io_log.configure(project=project)
        yield
    finally:
        _io_log.configure(project=old_project)


def replay_call_snapshot(
    call_id: int,
    *,
    trace_id: str,
    task: str | None = None,
    max_budget: float | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Replay one captured call snapshot through the shared runtime.

    Replay is intentionally call-level. If the original call depended on
    workflow state that never reached `llm_client`, the owning project must
    reconstruct that state first and then hand this module a prepared call.
    """

    record = get_call_record(call_id)
    snapshot = record["call_snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError(f"Call id {call_id} does not have a replayable call snapshot.")

    snapshot_version = snapshot.get("snapshot_version", 1)
    if type(snapshot_version) is not int or snapshot_version not in {1, 2, 3}:
        raise ValueError(
            f"Call id {call_id} has unsupported snapshot_version={snapshot_version!r}."
        )
    stored_fingerprint = record.get("call_fingerprint")
    observed_fingerprint = snapshot_fingerprint(snapshot)
    if not isinstance(stored_fingerprint, str) or not hmac.compare_digest(
        stored_fingerprint,
        observed_fingerprint,
    ):
        raise ValueError(
            f"Call id {call_id} call snapshot does not match its stored fingerprint."
        )

    unsupported_paths = _find_unsupported_diagnostic_paths(
        snapshot.get("request"),
        path="request",
    )
    if unsupported_paths:
        raise ValueError(
            f"Call id {call_id} contains a replay-unsupported normalized value at "
            f"{', '.join(unsupported_paths)}. Replay would substitute a different "
            "public-call value, so llm_client refuses it."
        )

    replay = snapshot.get("replay")
    validated_snapshot: _ReplaySnapshotV2 | _ReplaySnapshotV3 | None = None
    if snapshot_version in {2, 3}:
        try:
            replay_metadata = _ReplayMetadataV2.model_validate(replay)
        except Exception as error:
            raise ValueError(f"Call id {call_id} has invalid replay metadata: {error}") from error
        unsupported_keys = list(replay_metadata.unsupported_keys)
    else:
        unsupported_keys = (
            list(replay.get("unsupported_keys", []))
            if isinstance(replay, Mapping) and isinstance(replay.get("unsupported_keys"), list)
            else []
        )
    if unsupported_keys:
        joined = ", ".join(sorted(str(key) for key in unsupported_keys))
        raise ValueError(
            f"Call id {call_id} includes replay-unsupported kwargs: {joined}. "
            "Replay would not be exact, so llm_client refuses it."
        )
    if snapshot_version == 2:
        try:
            validated_snapshot = _ReplaySnapshotV2.model_validate(snapshot)
        except Exception as error:
            raise ValueError(f"Call id {call_id} has invalid v2 snapshot envelope: {error}") from error
    elif snapshot_version == 3:
        try:
            validated_snapshot = _ReplaySnapshotV3.model_validate(snapshot)
        except Exception as error:
            raise ValueError(f"Call id {call_id} has invalid v3 snapshot envelope: {error}") from error

    request = snapshot_request_identity(snapshot)
    messages = request.get("messages")
    control = request.get("control")
    public_kwargs = request.get("kwargs")
    if not isinstance(messages, list):
        raise ValueError(f"Call id {call_id} snapshot is missing request.messages.")
    if not isinstance(control, Mapping):
        raise ValueError(f"Call id {call_id} snapshot is missing request.control.")
    if not isinstance(public_kwargs, Mapping):
        raise ValueError(f"Call id {call_id} snapshot is missing request.kwargs.")

    if snapshot_version == 1 and (
        "retry_policy" in control or "cache_policy" in control
    ):
        raise ValueError(
            f"Call id {call_id} snapshot_version=1 cannot contain v2 replay policy fields."
        )

    public_api = (
        validated_snapshot.public_api
        if validated_snapshot is not None
        else str(snapshot.get("public_api", "call_llm"))
    )
    replay_policy: _ReplayExecutionPolicyV2 | None = None
    if validated_snapshot is not None:
        replay_policy = validated_snapshot.request.control
        expected_call_kind = _REPLAY_PUBLIC_API_CALL_KINDS.get(public_api)
        if validated_snapshot.call_kind != expected_call_kind:
            raise ValueError(
                f"Call id {call_id} public_api={public_api!r} requires "
                f"call_kind={expected_call_kind!r}."
            )
        reserved_kwargs = sorted(
            str(key) for key in public_kwargs if key in _REPLAY_RESERVED_PUBLIC_KWARGS
        )
        if reserved_kwargs:
            raise ValueError(
                f"Call id {call_id} request.kwargs contains reserved replay controls: "
                f"{', '.join(reserved_kwargs)}."
            )
        if (
            expected_call_kind == "structured"
            and replay_policy.structured_output_mode is None
        ):
            raise ValueError(
                f"Call id {call_id} has invalid replay-safe execution policy state: "
                "structured calls require structured_output_mode."
            )
        if expected_call_kind == "text" and (
            replay_policy.structured_output_mode is not None
            or request.get("response_model_fqn") is not None
            or request.get("response_model_schema") is not None
        ):
            raise ValueError(
                f"Call id {call_id} has invalid replay-safe execution policy state: "
                "text calls cannot carry structured response policy or schema state."
            )
        if expected_call_kind == "structured" and replay_policy.execution_mode is not None:
            raise ValueError(
                f"Call id {call_id} has invalid replay-safe execution policy state: "
                "structured calls cannot carry a text execution_mode."
            )
        if expected_call_kind == "text" and replay_policy.execution_mode is None:
            raise ValueError(
                f"Call id {call_id} has invalid replay-safe execution policy state: "
                "text calls require execution_mode."
            )

    if snapshot_version == 3 and max_budget is None:
        raise ValueError(
            f"Call id {call_id} v3 replay requires a fresh explicit max_budget; "
            "the captured original-call budget is identity, not new spend authority."
        )
    effective_replay_budget = 0.0 if max_budget is None else max_budget
    if (
        isinstance(effective_replay_budget, bool)
        or not isinstance(effective_replay_budget, (int, float))
        or not math.isfinite(effective_replay_budget)
        or effective_replay_budget < 0
    ):
        raise ValueError("replay max_budget must be a finite nonnegative number")

    replay_task = task or record["task"] or f"observability.replay.{snapshot.get('public_api', 'call')}"
    replay_project = project if project is not None else record["project"]
    if replay_policy is not None:
        call_kwargs: dict[str, Any] = {
            "timeout": replay_policy.timeout,
            "num_retries": replay_policy.num_retries,
            "reasoning_effort": replay_policy.reasoning_effort,
            "api_base": replay_policy.api_base,
            "base_delay": replay_policy.base_delay,
            "max_delay": replay_policy.max_delay,
            "retry_on": (
                list(replay_policy.retry_on)
                if replay_policy.retry_on is not None
                else None
            ),
            "fallback_models": (
                list(replay_policy.fallback_models)
                if replay_policy.fallback_models is not None
                else None
            ),
            "task": replay_task,
            "trace_id": trace_id,
            "max_budget": float(effective_replay_budget),
            "prompt_ref": request.get("prompt_ref"),
            **dict(public_kwargs),
        }
        replay_retry = replay_policy.retry_policy
        call_kwargs["retry"] = RetryPolicy(
            max_retries=replay_retry.max_retries,
            base_delay=replay_retry.base_delay,
            max_delay=replay_retry.max_delay,
            retry_on=(
                list(replay_retry.retry_on)
                if replay_retry.retry_on is not None
                else None
            ),
        )
        if replay_policy.cache_policy.mode != "disabled":
            raise ValueError(f"Call id {call_id} cannot reconstruct enabled cache state.")
        call_kwargs["cache"] = None
        if replay_policy.execution_mode is not None:
            call_kwargs["execution_mode"] = replay_policy.execution_mode
    else:
        call_kwargs = {
            "timeout": control.get("timeout", 60),
            "num_retries": control.get("num_retries", 0),
            "reasoning_effort": control.get("reasoning_effort"),
            "api_base": control.get("api_base"),
            "base_delay": control.get("base_delay", 1.0),
            "max_delay": control.get("max_delay", 30.0),
            "retry_on": control.get("retry_on"),
            "fallback_models": control.get("fallback_models"),
            "task": replay_task,
            "trace_id": trace_id,
            "max_budget": float(effective_replay_budget),
            "prompt_ref": request.get("prompt_ref"),
            **dict(public_kwargs),
        }

    structured_output_mode = (
        replay_policy.structured_output_mode
        if replay_policy is not None
        else control.get("structured_output_mode")
    )
    if structured_output_mode is not None:
        from llm_client.execution.call_contracts import StructuredOutputPolicy

        call_kwargs["structured_output_policy"] = StructuredOutputPolicy.model_validate(
            {"mode": structured_output_mode}
        )

    requested_model = request.get("requested_model")
    if not isinstance(requested_model, str) or not requested_model:
        raise ValueError(f"Call id {call_id} snapshot is missing request.requested_model.")

    with _temporary_project_override(replay_project):
        if public_api == "call_llm":
            result = _call_text_for_replay(requested_model, messages, **call_kwargs)
        elif public_api == "acall_llm":
            result = asyncio.run(_acall_text_for_replay(requested_model, messages, **call_kwargs))
        elif public_api == "call_llm_structured":
            response_model = _resolve_response_model_for_replay(
                request,
                call_id=call_id,
                snapshot_version=snapshot_version,
            )
            result = _call_structured_for_replay(
                requested_model,
                messages,
                response_model,
                **call_kwargs,
            )
        elif public_api == "acall_llm_structured":
            response_model = _resolve_response_model_for_replay(
                request,
                call_id=call_id,
                snapshot_version=snapshot_version,
            )
            result = asyncio.run(
                _acall_structured_for_replay(
                    requested_model,
                    messages,
                    response_model,
                    **call_kwargs,
                )
            )
        else:
            raise ValueError(
                f"Replay is not supported for public_api={public_api!r}. "
                "Only call_llm/acall_llm/call_llm_structured/acall_llm_structured are supported."
            )

    return {
        "source_call_id": call_id,
        "replay_trace_id": trace_id,
        "task": replay_task,
        "project": replay_project,
        "public_api": public_api,
        "result": result,
    }
