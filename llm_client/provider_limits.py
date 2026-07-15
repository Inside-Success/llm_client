"""Typed, secret-free provider-limit observation for shared runtime consumers.

This module owns generic credential-source inspection and the authenticated
OpenRouter current-key status read. It deliberately does not decide whether a
particular project may reserve or dispatch an attempt, and it never claims that
provider-reported state proves exact enforcement or an invoice ceiling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from llm_client.utils.openrouter import (
    OPENROUTER_API_BASE_ENV,
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_DEFAULT_API_BASE,
    _openrouter_key_sources_from_env,
)


OPENROUTER_CURRENT_KEY_URL = f"{OPENROUTER_DEFAULT_API_BASE}/key"


class ProviderLimitErrorCodeV1(str, Enum):
    """Stable, secret-free failure codes for provider-limit operations."""

    PROVIDER_READ_NOT_AUTHORIZED = "OPENROUTER_PROVIDER_READ_NOT_AUTHORIZED"
    CONFIG_INVALID = "OPENROUTER_PROVIDER_LIMIT_CONFIG_INVALID"
    KEYS_FILE_NOT_EXPLICIT = "OPENROUTER_KEYS_FILE_NOT_EXPLICIT"
    KEYS_FILE_NOT_ABSOLUTE = "OPENROUTER_KEYS_FILE_NOT_ABSOLUTE"
    KEYS_FILE_MISSING = "OPENROUTER_KEYS_FILE_MISSING"
    KEYS_FILE_SYMLINK = "OPENROUTER_KEYS_FILE_SYMLINK"
    KEYS_FILE_NOT_EMPTY = "OPENROUTER_KEYS_FILE_NOT_EMPTY"
    ROTATION_SOURCE_PRESENT = "OPENROUTER_ROTATION_SOURCE_PRESENT"
    KEY_COUNT_INVALID = "OPENROUTER_KEY_COUNT_INVALID"
    API_ORIGIN_INVALID = "OPENROUTER_API_ORIGIN_INVALID"
    PROVIDER_TRANSPORT = "OPENROUTER_PROVIDER_TRANSPORT_ERROR"
    PROVIDER_REDIRECT = "OPENROUTER_PROVIDER_REDIRECT"
    PROVIDER_HTTP_STATUS = "OPENROUTER_PROVIDER_HTTP_STATUS"
    PROVIDER_CONTENT_TYPE = "OPENROUTER_PROVIDER_CONTENT_TYPE_INVALID"
    PROVIDER_PAYLOAD_TOO_LARGE = "OPENROUTER_PROVIDER_PAYLOAD_TOO_LARGE"
    PROVIDER_PAYLOAD_INVALID = "OPENROUTER_PROVIDER_PAYLOAD_INVALID"
    PROVIDER_VALUE_INVALID = "OPENROUTER_PROVIDER_VALUE_INVALID"
    ENVIRONMENT_CHANGED = "OPENROUTER_ENVIRONMENT_CHANGED"


class ProviderLimitObservationErrorV1(RuntimeError):
    """Fail-loud provider observation error with no external or secret payload."""

    def __init__(self, code: ProviderLimitErrorCodeV1, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(f"{code.value}: {message}")

    def as_dict(self) -> dict[str, str]:
        """Return the stable agent-facing error envelope."""
        return {
            "schema_version": "provider-limit-observation-error-v1",
            "code": self.code.value,
            "message": self.public_message,
        }


class ProviderLimitObserverConfigV1(BaseModel):
    """Configurable local transport bounds for one current-key observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(
        default=10.0,
        description="Finite positive timeout for the single canonical provider read.",
    )
    max_response_bytes: int = Field(
        default=65_536,
        description="Maximum response body size accepted before JSON parsing.",
    )

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        return value

    @field_validator("max_response_bytes")
    @classmethod
    def _validate_response_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_response_bytes must be positive")
        return value


class OpenRouterKeyEnvironmentV1(BaseModel):
    """Secret-free post-import inventory for exactly one OpenRouter primary key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["openrouter-key-environment-v1"] = Field(
        default="openrouter-key-environment-v1",
        description="Version of the public environment inventory contract.",
    )
    key_count: Literal[1] = Field(
        description="Number of effective primary credentials after validation.",
    )
    key_fingerprint: str = Field(
        description="Full SHA-256 join for the normalized key; never a key suffix.",
    )
    configured_sources: tuple[str, ...] = Field(
        description="Non-secret environment variable names supplying the credential.",
    )
    rotation_sources_absent: Literal[True] = Field(
        description="True only when multi-key and numbered sources are absent.",
    )
    llm_client_keys_file_empty: Literal[True] = Field(
        description="True only for an explicit zero-byte regular non-symlink key file.",
    )
    inventory_phase: Literal["after_llm_client_import"] = Field(
        description="Lifecycle point at which import-time key loading has completed.",
    )


class OpenRouterKeyLimitObservationV1(BaseModel):
    """Strict public projection of provider-reported current-key state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["openrouter-key-limit-observation-v1"] = Field(
        default="openrouter-key-limit-observation-v1",
        description="Version of the strict provider observation contract.",
    )
    key_fingerprint: str = Field(
        description="SHA-256 join for the exact credential used by the request.",
    )
    provider_api_origin: Literal["https://openrouter.ai/api/v1"] = Field(
        description="Fixed canonical origin that produced the observation.",
    )
    observed_at_utc: AwareDatetime = Field(
        description="UTC timestamp assigned when the provider response was accepted.",
    )
    limit_usd: Decimal | None = Field(
        description="Provider-reported USD limit, or null when unlimited.",
    )
    limit_remaining_usd: Decimal | None = Field(
        description="Provider-reported remaining USD credit, or null when unlimited.",
    )
    limit_reset: str | None = Field(
        description="Provider-reported reset policy or null for non-resetting state.",
    )
    include_byok_in_limit: bool = Field(
        description="Whether BYOK usage is included in the reported limit.",
    )
    is_management_key: bool = Field(
        description="Provider-reported management-key classification.",
    )
    is_provisioning_key: bool = Field(
        description="Provider-reported provisioning-key classification.",
    )
    expires_at: AwareDatetime | None = Field(
        description="Provider-reported key expiry timestamp, when present.",
    )
    provider_limit_state_observed: Literal[True] = Field(
        default=True,
        description="True only after an authenticated current-key response is accepted.",
    )
    evidence_kind: Literal["authenticated_provider_read"] = Field(
        default="authenticated_provider_read",
        description="Evidence kind distinguishing a live read from a transport fixture.",
    )
    strict_invoice_ceiling_supported: Literal[False] = Field(
        default=False,
        description="Always false because reported state does not prove exact billing enforcement.",
    )


class OpenRouterProviderLimitPreflightV1(BaseModel):
    """One exact environment joined to one authenticated provider observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["openrouter-provider-limit-preflight-v1"] = Field(
        default="openrouter-provider-limit-preflight-v1",
        description="Version of the joined environment and observation envelope.",
    )
    environment: OpenRouterKeyEnvironmentV1 = Field(
        description="Validated post-import credential environment used by the read.",
    )
    observation: OpenRouterKeyLimitObservationV1 = Field(
        description="Strict provider-reported state for the same key fingerprint.",
    )


class _OpenRouterProviderKeyDataV1(BaseModel):
    """Permissive parser for the provider-owned current-key data object."""

    model_config = ConfigDict(extra="ignore")

    limit: Decimal | None = Field(description="Remote limit value or null.")
    limit_remaining: Decimal | None = Field(description="Remote remaining value or null.")
    limit_reset: str | None = Field(description="Remote reset value or null.")
    include_byok_in_limit: bool = Field(description="Remote BYOK inclusion flag.")
    is_management_key: bool = Field(description="Remote management-key flag.")
    is_provisioning_key: bool = Field(description="Remote provisioning-key flag.")
    expires_at: AwareDatetime | None = Field(description="Remote expiry timestamp or null.")

    @field_validator("limit", "limit_remaining")
    @classmethod
    def _validate_money(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or value < 0:
            raise ValueError("provider monetary values must be finite and nonnegative")
        return value


class _OpenRouterProviderResponseV1(BaseModel):
    """Permissive parser for the provider-owned response envelope."""

    model_config = ConfigDict(extra="ignore")

    data: _OpenRouterProviderKeyDataV1 = Field(
        description="Provider-owned current-key data payload.",
    )


def _error(code: ProviderLimitErrorCodeV1, message: str) -> ProviderLimitObservationErrorV1:
    """Construct one stable error without dynamic external content."""
    return ProviderLimitObservationErrorV1(code, message)


def _validated_environment_and_secret() -> tuple[OpenRouterKeyEnvironmentV1, str]:
    """Validate the post-import key environment and retain the secret privately."""
    raw_keys_file = os.environ.get("LLM_CLIENT_KEYS_FILE", "").strip()
    if not raw_keys_file:
        raise _error(
            ProviderLimitErrorCodeV1.KEYS_FILE_NOT_EXPLICIT,
            "LLM_CLIENT_KEYS_FILE must name an explicit empty file.",
        )
    keys_file = Path(raw_keys_file)
    if not keys_file.is_absolute():
        raise _error(
            ProviderLimitErrorCodeV1.KEYS_FILE_NOT_ABSOLUTE,
            "LLM_CLIENT_KEYS_FILE must be absolute.",
        )
    if keys_file.is_symlink():
        raise _error(
            ProviderLimitErrorCodeV1.KEYS_FILE_SYMLINK,
            "LLM_CLIENT_KEYS_FILE must not be a symlink.",
        )
    try:
        if not keys_file.is_file():
            raise _error(
                ProviderLimitErrorCodeV1.KEYS_FILE_MISSING,
                "LLM_CLIENT_KEYS_FILE must be an existing regular file.",
            )
        size = keys_file.stat().st_size
    except OSError as exc:
        raise _error(
            ProviderLimitErrorCodeV1.KEYS_FILE_MISSING,
            "LLM_CLIENT_KEYS_FILE could not be inspected.",
        ) from exc
    if size != 0:
        raise _error(
            ProviderLimitErrorCodeV1.KEYS_FILE_NOT_EMPTY,
            "LLM_CLIENT_KEYS_FILE must be zero bytes.",
        )

    configured_origin = os.environ.get(OPENROUTER_API_BASE_ENV, "").strip().rstrip("/")
    if configured_origin and configured_origin != OPENROUTER_DEFAULT_API_BASE:
        raise _error(
            ProviderLimitErrorCodeV1.API_ORIGIN_INVALID,
            "OPENROUTER_API_BASE must be the canonical OpenRouter API origin.",
        )

    sources = _openrouter_key_sources_from_env()
    if any(source.rotation_source for source in sources):
        raise _error(
            ProviderLimitErrorCodeV1.ROTATION_SOURCE_PRESENT,
            "Multi-key and numbered OpenRouter credential sources are forbidden.",
        )
    primary_values = [
        value
        for source in sources
        if source.name == OPENROUTER_API_KEY_ENV
        for value in source.values
    ]
    if len(primary_values) != 1:
        raise _error(
            ProviderLimitErrorCodeV1.KEY_COUNT_INVALID,
            "Exactly one OpenRouter primary key is required.",
        )
    secret = primary_values[0]
    fingerprint = f"sha256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()}"
    environment = OpenRouterKeyEnvironmentV1(
        key_count=1,
        key_fingerprint=fingerprint,
        configured_sources=(OPENROUTER_API_KEY_ENV,),
        rotation_sources_absent=True,
        llm_client_keys_file_empty=True,
        inventory_phase="after_llm_client_import",
    )
    return environment, secret


def inspect_openrouter_key_environment_v1() -> OpenRouterKeyEnvironmentV1:
    """Return one secret-free post-import OpenRouter environment inventory.

    This operation is deterministic and provider-free. It fails before network
    access whenever key origin, source multiplicity, or key-file state is ambiguous.
    """
    environment, _secret = _validated_environment_and_secret()
    return environment


def _parse_provider_response(response: httpx.Response, config: ProviderLimitObserverConfigV1) -> _OpenRouterProviderResponseV1:
    """Validate transport metadata and parse exact provider JSON lexemes."""
    if 300 <= response.status_code < 400:
        raise _error(
            ProviderLimitErrorCodeV1.PROVIDER_REDIRECT,
            "Provider redirects are not accepted.",
        )
    if response.status_code != 200:
        raise _error(
            ProviderLimitErrorCodeV1.PROVIDER_HTTP_STATUS,
            "Provider returned a non-success status.",
        )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/json", "application/problem+json"}:
        raise _error(
            ProviderLimitErrorCodeV1.PROVIDER_CONTENT_TYPE,
            "Provider response content type is not JSON.",
        )
    content = bytearray()
    for chunk in response.iter_bytes():
        if len(content) + len(chunk) > config.max_response_bytes:
            raise _error(
                ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_TOO_LARGE,
                "Provider response exceeds the configured size bound.",
            )
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=Decimal,
        )
        return _OpenRouterProviderResponseV1.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        if isinstance(exc, ValidationError) and any(
            item.get("loc", ())[-1:] in {("limit",), ("limit_remaining",)}
            for item in exc.errors()
        ):
            code = ProviderLimitErrorCodeV1.PROVIDER_VALUE_INVALID
            message = "Provider monetary state is invalid."
        else:
            code = ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_INVALID
            message = "Provider response does not match the current-key contract."
        raise _error(code, message) from exc


def _observe_openrouter_key_limit_with_transport_v1(
    *,
    allow_provider_read: bool,
    config: ProviderLimitObserverConfigV1 | None = None,
    transport: httpx.BaseTransport | None = None,
    observed_at: datetime | None = None,
) -> OpenRouterProviderLimitPreflightV1:
    """Observe current-key state with an optional private test transport seam."""
    if not allow_provider_read:
        raise _error(
            ProviderLimitErrorCodeV1.PROVIDER_READ_NOT_AUTHORIZED,
            "An explicit provider-read authorization is required.",
        )
    resolved_config = config or ProviderLimitObserverConfigV1()
    environment_before, secret = _validated_environment_and_secret()
    try:
        with httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=resolved_config.timeout_seconds,
            transport=transport,
        ) as client:
            with client.stream(
                "GET",
                OPENROUTER_CURRENT_KEY_URL,
                headers={
                    "authorization": f"Bearer {secret}",
                    "accept": "application/json",
                },
            ) as response:
                parsed = _parse_provider_response(response, resolved_config)
    except httpx.HTTPError as exc:
        raise _error(
            ProviderLimitErrorCodeV1.PROVIDER_TRANSPORT,
            "Provider current-key transport failed.",
        ) from exc

    environment_after, _secret_after = _validated_environment_and_secret()
    if environment_after != environment_before:
        raise _error(
            ProviderLimitErrorCodeV1.ENVIRONMENT_CHANGED,
            "OpenRouter credential environment changed during observation.",
        )
    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise _error(
            ProviderLimitErrorCodeV1.CONFIG_INVALID,
            "Observation timestamp must be timezone-aware.",
        )
    data = parsed.data
    observation = OpenRouterKeyLimitObservationV1(
        key_fingerprint=environment_before.key_fingerprint,
        provider_api_origin="https://openrouter.ai/api/v1",
        observed_at_utc=timestamp.astimezone(timezone.utc),
        limit_usd=data.limit,
        limit_remaining_usd=data.limit_remaining,
        limit_reset=data.limit_reset,
        include_byok_in_limit=data.include_byok_in_limit,
        is_management_key=data.is_management_key,
        is_provisioning_key=data.is_provisioning_key,
        expires_at=data.expires_at,
    )
    return OpenRouterProviderLimitPreflightV1(
        environment=environment_before,
        observation=observation,
    )


def observe_openrouter_key_limit_v1(
    *,
    allow_provider_read: bool,
    config: ProviderLimitObserverConfigV1 | None = None,
) -> OpenRouterProviderLimitPreflightV1:
    """Perform one explicitly authorized canonical OpenRouter current-key read.

    The returned envelope reports provider state only. It does not authorize an
    inference call, compare an attempt allocation, or prove provider enforcement.
    """
    return _observe_openrouter_key_limit_with_transport_v1(
        allow_provider_read=allow_provider_read,
        config=config,
    )


__all__ = [
    "OPENROUTER_CURRENT_KEY_URL",
    "OpenRouterKeyEnvironmentV1",
    "OpenRouterKeyLimitObservationV1",
    "OpenRouterProviderLimitPreflightV1",
    "ProviderLimitErrorCodeV1",
    "ProviderLimitObservationErrorV1",
    "ProviderLimitObserverConfigV1",
    "inspect_openrouter_key_environment_v1",
    "observe_openrouter_key_limit_v1",
]
