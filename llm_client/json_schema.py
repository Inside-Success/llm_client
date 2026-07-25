"""Structured LLM calls for callers that own JSON Schema outside Python.

The established structured runtime accepts Pydantic response models. This
module adapts a caller-supplied JSON Schema into a dynamic Pydantic root model
so provider routing, schema projection, repair retries, observability, budgets,
and cost accounting continue to use that runtime unchanged.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, ClassVar, TypeAlias, cast

from jsonschema import SchemaError
from jsonschema.validators import validator_for
from pydantic import RootModel, model_validator

from llm_client.core.client import (
    acall_llm_structured,
    call_llm_structured,
)
from llm_client.core.data_types import LLMCallResult
from llm_client.execution.call_contracts import StructuredOutputPolicy


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_STRICT_NATIVE_POLICY = StructuredOutputPolicy(mode="require_native_json_schema")


def _format_schema_validation_errors(errors: list[Any]) -> str:
    """Render bounded, deterministic JSON Schema validation diagnostics."""
    rendered: list[str] = []
    for error in errors[:8]:
        path = "/".join(str(part) for part in error.absolute_path)
        location = f"/{path}" if path else "/"
        rendered.append(f"{location}: {error.message}")
    if len(errors) > 8:
        rendered.append(f"... and {len(errors) - 8} more error(s)")
    return "; ".join(rendered)


def json_schema_response_model(
    response_schema: dict[str, Any],
    *,
    schema_name: str = "response_schema",
) -> type[RootModel[Any]]:
    """Create a Pydantic root model backed by one caller-owned JSON Schema.

    The returned model exposes an isolated copy of ``response_schema`` through
    ``model_json_schema()``. The existing structured runtime therefore applies
    its normal direct-provider/OpenRouter projection. Parsed values are checked
    against the original schema locally; violations become Pydantic validation
    errors and enter the runtime's established repair-retry path.
    """
    if not _SCHEMA_NAME_PATTERN.fullmatch(schema_name):
        raise ValueError(
            "schema_name must start with a letter or underscore, contain only "
            "letters, digits, or underscores, and be at most 64 characters."
        )
    if not isinstance(response_schema, dict):
        raise ValueError("response_schema must be a JSON object.")

    schema = deepcopy(response_schema)
    validator_class = validator_for(schema)
    try:
        validator_class.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid JSON Schema: {error.message}") from error
    schema_validator = validator_class(schema)

    class JsonSchemaResponse(RootModel[Any]):
        _response_schema: ClassVar[dict[str, Any]] = schema
        _schema_validator: ClassVar[Any] = schema_validator

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            return deepcopy(cls._response_schema)

        @model_validator(mode="after")
        def validate_response_schema(self) -> "JsonSchemaResponse":
            errors = sorted(
                self._schema_validator.iter_errors(self.root),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if errors:
                raise ValueError(_format_schema_validation_errors(errors))
            return self

    JsonSchemaResponse.__name__ = schema_name
    JsonSchemaResponse.__qualname__ = schema_name
    JsonSchemaResponse.__module__ = __name__
    return JsonSchemaResponse


def call_llm_json_schema(
    model: str,
    messages: list[dict[str, Any]],
    response_schema: dict[str, Any],
    *,
    schema_name: str = "response_schema",
    structured_output_policy: StructuredOutputPolicy | None = None,
    **kwargs: Any,
) -> tuple[JsonValue, LLMCallResult]:
    """Return JSON validated against a caller-supplied JSON Schema.

    Provider-native strict JSON Schema is required by default. Callers may pass
    an explicit ``StructuredOutputPolicy`` when they intentionally permit the
    established automatic fallback behavior.
    """
    response_model = json_schema_response_model(
        response_schema,
        schema_name=schema_name,
    )
    parsed, result = call_llm_structured(
        model,
        messages,
        response_model,
        structured_output_policy=structured_output_policy or _STRICT_NATIVE_POLICY,
        **kwargs,
    )
    return cast(JsonValue, parsed.root), result


async def acall_llm_json_schema(
    model: str,
    messages: list[dict[str, Any]],
    response_schema: dict[str, Any],
    *,
    schema_name: str = "response_schema",
    structured_output_policy: StructuredOutputPolicy | None = None,
    **kwargs: Any,
) -> tuple[JsonValue, LLMCallResult]:
    """Async counterpart to :func:`call_llm_json_schema`."""
    response_model = json_schema_response_model(
        response_schema,
        schema_name=schema_name,
    )
    parsed, result = await acall_llm_structured(
        model,
        messages,
        response_model,
        structured_output_policy=structured_output_policy or _STRICT_NATIVE_POLICY,
        **kwargs,
    )
    return cast(JsonValue, parsed.root), result
