"""Responses API helper utilities for ``llm_client``.

This module owns the OpenAI Responses API helper cluster: strict schema
preparation, message/tool/response-format conversion, responses-kwargs
construction, usage/cost extraction, and result finalization. Policy helpers
are imported directly from ``call_contracts``, ``model_detection``, and
``background_runtime``.
"""

from __future__ import annotations

from copy import deepcopy
import json as _json
import logging
from typing import Any

import litellm
from pydantic import BaseModel

from llm_client.execution.background_runtime import _needs_background_mode
from llm_client.execution.call_contracts import (
    _GPT5_REASONING_GATED_SAMPLING,
    _coerce_model_incompatible_params,
    _raise_empty_response,
    _resolve_unsupported_param_policy,
    _strip_llm_internal_kwargs,
)
from llm_client.utils.cost_utils import (
    FALLBACK_COST_FLOOR_USD_PER_TOKEN,
    _add_token_details,
    _parse_cost_result,
    _provider_reported_cost,
)
from llm_client.core.data_types import LLMCallResult
from llm_client.execution.retry import _EMPTY_POLICY_FINISH_REASONS, _EMPTY_TOOL_PROTOCOL_FINISH_REASONS
from llm_client.utils.openrouter import _enable_openrouter_inline_metadata

logger = logging.getLogger(__name__)


_PROVIDER_UNSUPPORTED_VALUE_CONSTRAINTS = frozenset({
    "exclusiveMaximum",
    "exclusiveMinimum",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "multipleOf",
    "pattern",
})


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add additionalProperties: false to all objects for OpenAI strict mode."""

    if schema.get("type") == "object":
        if "properties" in schema:
            schema["additionalProperties"] = False
            schema["required"] = list(schema["properties"].keys())
            for prop in schema["properties"].values():
                _strict_json_schema(prop)
        elif isinstance(schema.get("additionalProperties"), dict):
            _strict_json_schema(schema["additionalProperties"])
        else:
            schema["additionalProperties"] = False
    if "items" in schema:
        _strict_json_schema(schema["items"])
    for combinator in ("anyOf", "allOf", "oneOf"):
        for sub_schema in schema.get(combinator, []):
            _strict_json_schema(sub_schema)
    for defn in schema.get("$defs", {}).values():
        _strict_json_schema(defn)
    return schema


def _strict_openai_response_model_schema(
    response_model: type[BaseModel],
) -> dict[str, Any]:
    """Return the OpenAI SDK's provider-compatible strict Pydantic schema.

    The SDK normalizer resolves a Pydantic ``$ref`` when a field-level
    description is its sibling and removes unsupported ``None`` defaults.
    Our generic dictionary helper does neither, and direct Responses rejects
    those shapes before generation.
    """
    from openai.lib._pydantic import to_strict_json_schema

    return to_strict_json_schema(response_model)


def _provider_compatible_discriminated_union_schema(
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Project provably disjoint ``oneOf`` unions onto provider-safe ``anyOf``.

    Some OpenAI-compatible structured-output routes reject ``oneOf`` even when
    Pydantic emits it for a discriminated union.  ``anyOf`` has identical
    acceptance semantics when every branch requires the same property with a
    distinct literal value.  Rewrite only that provable case; leave arbitrary
    or overlapping ``oneOf`` schemas unchanged so unsupported contracts still
    fail visibly at the provider boundary.  Callers continue to validate the
    response with the original Pydantic model.
    """

    projected = deepcopy(schema)
    _project_disjoint_one_of_unions(projected, root=projected, visited=set())
    return projected


def _project_disjoint_one_of_unions(
    node: dict[str, Any],
    *,
    root: dict[str, Any],
    visited: set[int],
) -> None:
    """Mutate one private schema copy without expanding internal references."""

    node_identity = id(node)
    if node_identity in visited:
        return
    visited.add(node_identity)

    branches = node.get("oneOf")
    if isinstance(branches, list) and len(branches) >= 2:
        resolved = [
            _resolve_local_schema_branch(branch, root)
            for branch in branches
            if isinstance(branch, dict)
        ]
        if len(resolved) == len(branches) and _branches_have_disjoint_literals(
            resolved,
            discriminator=node.get("discriminator"),
        ):
            node["anyOf"] = node.pop("oneOf")
            node.pop("discriminator", None)

    for value in node.values():
        if isinstance(value, dict):
            _project_disjoint_one_of_unions(value, root=root, visited=visited)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _project_disjoint_one_of_unions(item, root=root, visited=visited)


def _resolve_local_schema_branch(
    branch: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a bare local JSON Pointer used by Pydantic union branches."""

    ref = branch.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/") or len(branch) != 1:
        return branch
    current: Any = root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return branch
        current = current[part]
    return current if isinstance(current, dict) else branch


def _branches_have_disjoint_literals(
    branches: list[dict[str, Any]],
    *,
    discriminator: Any,
) -> bool:
    """Return true only for a common required property with unique constants."""

    requested_property: str | None = None
    if isinstance(discriminator, dict):
        property_name = discriminator.get("propertyName")
        if isinstance(property_name, str) and property_name:
            requested_property = property_name

    candidates: set[str] | None = None
    for branch in branches:
        properties = branch.get("properties")
        required = branch.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            return False
        literal_properties = {
            name
            for name, value in properties.items()
            if name in required and isinstance(value, dict) and "const" in value
        }
        candidates = (
            literal_properties
            if candidates is None
            else candidates.intersection(literal_properties)
        )

    if requested_property is not None:
        if not candidates or requested_property not in candidates:
            return False
        candidates = {requested_property}
    if not candidates:
        return False

    for property_name in candidates:
        values = [branch["properties"][property_name]["const"] for branch in branches]
        try:
            if len(set(values)) == len(values):
                return True
        except TypeError:
            continue
    return False


def _openrouter_compatible_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Project a strict schema onto OpenRouter's structural subset.

    OpenRouter's provider routes reject value-level JSON Schema constraints such
    as ``minimum`` for some native-schema backends.  Those constraints are not
    reliably decode-enforced by providers in any case; callers still validate
    the returned JSON with the original Pydantic response model.  Keep the
    structural contract (objects, properties, required fields, enums, and
    additional-properties policy) in the provider request while retaining the
    full local validation contract.
    """

    projected = _provider_compatible_discriminated_union_schema(schema)
    _project_openrouter_compatible_schema(projected)
    return projected


def _project_openrouter_compatible_schema(schema: dict[str, Any]) -> None:
    """Mutate one private schema copy onto OpenRouter's structural subset."""

    for key in _PROVIDER_UNSUPPORTED_VALUE_CONSTRAINTS:
        schema.pop(key, None)
    if not schema:
        raise ValueError(
            "OpenRouter native JSON Schema cannot represent an unconstrained "
            "value schema; define an explicit structural response contract."
        )
    for value in schema.values():
        if isinstance(value, dict):
            _project_openrouter_compatible_schema(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _project_openrouter_compatible_schema(item)


def _convert_messages_to_input(messages: list[dict[str, Any]]) -> str:
    """Convert chat messages to a single input string for the Responses API."""

    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(f"User: {content}")
    return "\n\n".join(parts)


def _convert_response_format_for_responses(
    response_format: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert chat-completions response_format to Responses API text.format."""

    if not response_format:
        return {"format": {"type": "text"}}

    if response_format.get("type") == "json_object":
        return {"format": {"type": "text"}}

    if response_format.get("type") == "json_schema":
        json_schema = response_format.get("json_schema", {})
        return {
            "format": {
                "type": "json_schema",
                "name": json_schema.get("name", "response_schema"),
                "schema": json_schema.get("schema", {}),
                "strict": json_schema.get("strict", True),
            }
        }

    return {"format": {"type": "text"}}


def _convert_tools_for_responses_api(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten Chat Completions tool schemas into Responses API function schemas."""

    converted = []
    for tool in tools:
        if "function" in tool and isinstance(tool["function"], dict):
            flat = {"type": tool.get("type", "function")}
            flat.update(tool["function"])
            converted.append(flat)
        else:
            converted.append(tool)
    return converted


def _prepare_responses_kwargs(
    model: str,
    messages: list[dict[str, Any]],
    *,
    timeout: int,
    reasoning_effort: str | None,
    api_base: str | None,
    kwargs: dict[str, Any],
    warning_sink: list[str] | None = None,
) -> dict[str, Any]:
    """Build kwargs for ``litellm.responses()`` / ``litellm.aresponses()``."""

    provider_kwargs = _strip_llm_internal_kwargs(kwargs)
    policy = _resolve_unsupported_param_policy(
        provider_kwargs.pop("unsupported_param_policy", None)
    )
    _coerce_model_incompatible_params(
        model=model,
        kwargs=provider_kwargs,
        policy=policy,
        warning_sink=warning_sink,
    )

    resp_kwargs: dict[str, Any] = {
        "model": model,
        "input": _convert_messages_to_input(messages),
    }
    if timeout > 0:
        resp_kwargs["timeout"] = timeout
    if api_base is not None:
        resp_kwargs["api_base"] = api_base

    response_format = provider_kwargs.pop("response_format", None)
    if response_format:
        resp_kwargs["text"] = _convert_response_format_for_responses(response_format)

    effort = reasoning_effort
    if effort is None:
        effort = provider_kwargs.pop("reasoning_effort", None)
    else:
        provider_kwargs.pop("reasoning_effort", None)
    if effort and model in _GPT5_REASONING_GATED_SAMPLING:
        resp_kwargs["reasoning"] = {"effort": effort}

    if _needs_background_mode(model, effort):
        resp_kwargs["background"] = True

    for key in (
        "max_tokens",
        "max_output_tokens",
        "messages",
        "thinking",
        "temperature",
        "unsupported_param_policy",
        "background_timeout",
        "background_poll_interval",
    ):
        provider_kwargs.pop(key, None)

    if "tools" in provider_kwargs:
        provider_kwargs["tools"] = _convert_tools_for_responses_api(provider_kwargs["tools"])

    resp_kwargs.update(provider_kwargs)
    _enable_openrouter_inline_metadata(model, resp_kwargs)
    return resp_kwargs


def _extract_responses_usage(response: Any) -> dict[str, Any]:
    """Extract token usage from a Responses API response."""

    usage = getattr(response, "usage", None)
    if usage is not None:
        result = {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        _add_token_details(
            result,
            prompt_details=getattr(usage, "input_tokens_details", None),
            completion_details=getattr(usage, "output_tokens_details", None),
        )
        return result
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _compute_responses_cost(response: Any, usage: dict[str, Any]) -> tuple[float, str]:
    """Compute Responses cost with the same precedence as Completions."""

    provider_cost = _provider_reported_cost(response)
    if provider_cost is not None:
        return provider_cost, "provider_reported"

    try:
        cost = float(litellm.completion_cost(completion_response=response))
        if cost > 0:
            return cost, "computed"
    except Exception:
        pass

    total = usage["total_tokens"]
    fallback = total * FALLBACK_COST_FLOOR_USD_PER_TOKEN
    if total > 0:
        logger.warning(
            "completion_cost failed for responses API, using fallback: $%.6f for %d tokens",
            fallback,
            total,
        )
    return fallback, "fallback_estimate"


def _build_result_from_responses(
    response: Any,
    model: str,
    *,
    warnings: list[str] | None = None,
) -> LLMCallResult:
    """Build ``LLMCallResult`` from a Responses API response."""

    def _item_get(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _extract_responses_tool_calls(resp: Any) -> list[dict[str, Any]]:
        output_items = getattr(resp, "output", None) or []
        tool_calls: list[dict[str, Any]] = []
        for idx, item in enumerate(output_items):
            item_type = _item_get(item, "type")
            if item_type not in {"function_call", "tool_call", "function"}:
                continue

            fn_name = _item_get(item, "name")
            fn_args = _item_get(item, "arguments")
            if not fn_name:
                fn_obj = _item_get(item, "function")
                if fn_obj is not None:
                    if isinstance(fn_obj, dict):
                        fn_name = fn_obj.get("name")
                        fn_args = fn_args if fn_args is not None else fn_obj.get("arguments")
                    else:
                        fn_name = getattr(fn_obj, "name", fn_name)
                        fn_args = fn_args if fn_args is not None else getattr(fn_obj, "arguments", None)
            if not fn_name:
                continue

            if fn_args is None:
                args_raw = "{}"
            elif isinstance(fn_args, str):
                args_raw = fn_args
            else:
                try:
                    args_raw = _json.dumps(fn_args)
                except Exception:
                    args_raw = str(fn_args)

            call_id = _item_get(item, "call_id") or _item_get(item, "id") or f"call_{idx}"
            tool_calls.append(
                {
                    "id": str(call_id),
                    "type": "function",
                    "function": {
                        "name": str(fn_name),
                        "arguments": args_raw,
                    },
                }
            )
        return tool_calls

    content = getattr(response, "output_text", None) or ""
    tool_calls = _extract_responses_tool_calls(response)

    usage = _extract_responses_usage(response)
    cost, cost_source = _parse_cost_result(
        _compute_responses_cost(response, usage),
        default_source="computed",
    )

    status = getattr(response, "status", "completed")
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = str(getattr(details, "reason", "")) if details else ""
        if "max_output_tokens" in reason and not tool_calls:
            raise RuntimeError(
                f"LLM response truncated ({len(content)} chars). Responses API hit max_output_tokens limit."
            )
        finish_reason = "length"
    else:
        finish_reason = "stop"

    if tool_calls:
        finish_reason = "tool_calls"

    if not content.strip() and not tool_calls:
        detail_reason = ""
        if status == "incomplete":
            details = getattr(response, "incomplete_details", None)
            detail_reason = str(getattr(details, "reason", "")).strip().lower() if details else ""
        diagnostics = {
            "model": model,
            "status": status,
            "finish_reason": finish_reason,
            "incomplete_reason": detail_reason or None,
            "output_items": len(getattr(response, "output", None) or []),
        }
        if detail_reason in _EMPTY_POLICY_FINISH_REASONS or finish_reason in _EMPTY_POLICY_FINISH_REASONS:
            _raise_empty_response(
                provider="responses_api",
                classification="provider_policy_block",
                retryable=False,
                diagnostics=diagnostics,
            )
        if detail_reason in _EMPTY_TOOL_PROTOCOL_FINISH_REASONS:
            _raise_empty_response(
                provider="responses_api",
                classification="provider_tool_protocol",
                retryable=False,
                diagnostics=diagnostics,
            )
        _raise_empty_response(
            provider="responses_api",
            classification="provider_empty_unknown",
            retryable=True,
            diagnostics=diagnostics,
        )

    logger.debug(
        "LLM call (responses API): model=%s tokens=%d cost=$%.6f status=%s tool_calls=%d",
        model,
        usage["total_tokens"],
        cost,
        status,
        len(tool_calls),
    )

    return LLMCallResult(
        content=content,
        usage=usage,
        cost=cost,
        model=model,
        resolved_model=model,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        raw_response=response,
        warnings=warnings or [],
        cost_source=cost_source,
    )
