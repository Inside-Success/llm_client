"""Versioned stdin/stdout bridge for JSON-Schema-native LLM calls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm_client.json_schema import JsonValue, call_llm_json_schema


PROTOCOL_VERSION = "1.0"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_ERROR_MESSAGE_CHARS = 4_000
_SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class JsonSchemaCallMessage(BaseModel):
    """One provider-neutral prompt message."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    content: str


class JsonSchemaCallRequest(BaseModel):
    """Strict wire request accepted by ``json-schema-call``."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    protocol_version: Literal["1.0"]
    model: str = Field(min_length=1)
    messages: list[JsonSchemaCallMessage] = Field(min_length=1)
    response_schema: dict[str, Any]
    schema_name: str = "response_schema"
    task: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    max_budget: float = Field(ge=0)
    timeout: int = Field(default=300, gt=0)
    num_retries: int = Field(default=2, ge=0)
    reasoning_effort: str | None = None
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    model_justification: str | None = Field(default=None, min_length=1)


def _read_request(path_value: str) -> str:
    if path_value == "-":
        text = sys.stdin.read(MAX_REQUEST_BYTES + 1)
        raw = text.encode("utf-8")
    else:
        path = Path(path_value).expanduser().resolve()
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError(
            f"Request exceeds the {MAX_REQUEST_BYTES}-byte input limit."
        )
    return text


def _write_error(code: str, error: Exception) -> None:
    message = str(error) or type(error).__name__
    for name, value in os.environ.items():
        if (
            len(value) >= 8
            and any(marker in name.upper() for marker in _SECRET_ENV_MARKERS)
        ):
            message = message.replace(value, "[redacted]")
    payload = {
        "protocolVersion": PROTOCOL_VERSION,
        "error": {
            "code": code,
            "message": message[:MAX_ERROR_MESSAGE_CHARS],
            "type": type(error).__name__,
        },
    }
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def _result_metadata(result: Any) -> dict[str, Any]:
    return {
        "requestedModel": result.requested_model or result.model,
        "resolvedModel": result.resolved_model or result.model,
        "logicalCallId": result.logical_call_id,
        "routingTrace": result.routing_trace,
        "usage": result.usage,
        "cost": result.cost,
        "marginalCost": result.marginal_cost,
        "costSource": result.cost_source,
        "costCoversAllAttempts": result.cost_covers_all_attempts,
        "finishReason": result.finish_reason,
        "warnings": result.warnings,
    }


def execute_json_schema_call(request: JsonSchemaCallRequest) -> dict[str, Any]:
    """Execute one validated bridge request and return its wire envelope."""
    provider_kwargs: dict[str, Any] = {}
    for name in ("reasoning_effort", "temperature", "seed", "max_tokens"):
        value = getattr(request, name)
        if value is not None:
            provider_kwargs[name] = value
    if request.model_justification is not None:
        provider_kwargs["model_justification"] = request.model_justification

    payload, result = call_llm_json_schema(
        request.model,
        [message.model_dump() for message in request.messages],
        request.response_schema,
        schema_name=request.schema_name,
        task=request.task,
        trace_id=request.trace_id,
        max_budget=request.max_budget,
        timeout=request.timeout,
        num_retries=request.num_retries,
        **provider_kwargs,
    )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "payload": payload,
        "metadata": _result_metadata(result),
    }


def cmd_json_schema_call(args: argparse.Namespace) -> None:
    """Read one request, execute it, and emit exactly one JSON result."""
    try:
        request = JsonSchemaCallRequest.model_validate_json(_read_request(args.request))
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        _write_error("request.invalid", error)
        raise SystemExit(2) from error

    try:
        response: dict[str, JsonValue | dict[str, Any] | str] = (
            execute_json_schema_call(request)
        )
        print(json.dumps(response, separators=(",", ":"), sort_keys=True))
    except Exception as error:
        _write_error("call.failed", error)
        raise SystemExit(1) from error


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "json-schema-call",
        help="Execute one strict structured call from a versioned JSON request.",
    )
    parser.add_argument(
        "--request",
        default="-",
        help="Request JSON path, or '-' for stdin (default).",
    )
    parser.set_defaults(handler=cmd_json_schema_call)
