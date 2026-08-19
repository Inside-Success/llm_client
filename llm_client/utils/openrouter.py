"""OpenRouter key rotation, routing, and detection utilities.

Manages the OpenRouter API key ring, key rotation on quota exhaustion,
and routing detection. These are extracted from client.py for concern
separation; client.py re-exports everything for backward compatibility.

This module depends on retry._error_status_code for status code extraction.
It must not import from client.py directly.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from llm_client.core.errors import LLMConfigurationError
from llm_client.execution.call_contracts import OpenRouterRoutePolicyV1
from llm_client.execution.retry import _error_status_code
from llm_client.utils.openrouter_accounts import (
    ACCOUNT_KEY_ENV,
    account_api_key,
    resolve_account,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (also defined in client.py — canonical home is here)
# ---------------------------------------------------------------------------

OPENROUTER_ROUTING_ENV = "LLM_CLIENT_OPENROUTER_ROUTING"
OPENROUTER_DEFAULT_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_API_BASE_ENV = "OPENROUTER_API_BASE"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_API_KEYS_ENV = "OPENROUTER_API_KEYS"
OPENROUTER_METADATA_HEADER = "X-OpenRouter-Metadata"
OPENROUTER_RESPONSE_CACHE_HEADER = "X-OpenRouter-Cache"
OPENROUTER_RESPONSE_CACHE_TTL_HEADER = "X-OpenRouter-Cache-TTL"
OPENROUTER_RESPONSE_CACHE_CLEAR_HEADER = "X-OpenRouter-Cache-Clear"
_OPENROUTER_NORMALIZED_PASSTHROUGH_PARAMS = frozenset({"reasoning_effort"})

# ---------------------------------------------------------------------------
# Module-level state for key rotation
# ---------------------------------------------------------------------------

_OPENROUTER_KEY_ROTATION_LOCK = threading.Lock()
_OPENROUTER_KEY_RING: tuple[str, ...] = ()
_OPENROUTER_KEY_RING_INDEX: int = 0


@dataclass(frozen=True)
class _OpenRouterKeySource:
    """One configured OpenRouter credential source and its normalized secrets.

    The structure is intentionally private because secret values must never cross
    the public provider-observation boundary. Keeping source identity before ring
    deduplication lets callers detect forbidden rotation configuration even when
    two sources contain the same secret.
    """

    name: str
    values: tuple[str, ...]
    rotation_source: bool


# ---------------------------------------------------------------------------
# Key normalization and splitting
# ---------------------------------------------------------------------------


def _normalize_api_key_value(value: Any) -> str:
    """Normalize API key env/input values."""
    return str(value or "").strip().strip("\"'")


def _split_api_keys(raw: str) -> list[str]:
    """Split comma/semicolon/newline-delimited key lists."""
    normalized: list[str] = []
    for part in re.split(r"[,\n;]", raw):
        value = _normalize_api_key_value(part)
        if value:
            normalized.append(value)
    return normalized


# ---------------------------------------------------------------------------
# Key discovery
# ---------------------------------------------------------------------------


def _routed_account_key() -> tuple[str, str | None] | None:
    """Return ``(account, key_or_None)`` when per-account credentials are configured.

    Account routing stays entirely dormant until at least one per-account
    credential exists, so the routing table is never consulted -- and can never
    break key resolution -- for a process that has not adopted it. Once adopted,
    a routing table that cannot be trusted raises rather than guessing which
    account to bill. Whether a missing credential for the owning account is fatal
    depends on what else is in the ring, so that decision belongs to the caller.
    """

    if not any(os.environ.get(env_name, "").strip() for env_name in ACCOUNT_KEY_ENV.values()):
        return None
    account = resolve_account()
    return account, account_api_key(account)


def _openrouter_key_sources_from_env() -> tuple[_OpenRouterKeySource, ...]:
    """Collect non-empty OpenRouter credential sources before deduplication."""
    sources: list[_OpenRouterKeySource] = []

    raw_multi = _normalize_api_key_value(os.environ.get(OPENROUTER_API_KEYS_ENV))
    if raw_multi:
        values = tuple(_split_api_keys(raw_multi))
        if values:
            sources.append(
                _OpenRouterKeySource(
                    name=OPENROUTER_API_KEYS_ENV,
                    values=values,
                    rotation_source=True,
                )
            )

    primary = _normalize_api_key_value(os.environ.get(OPENROUTER_API_KEY_ENV))
    if primary:
        sources.append(
            _OpenRouterKeySource(
                name=OPENROUTER_API_KEY_ENV,
                values=(primary,),
                rotation_source=False,
            )
        )

    numbered_re = re.compile(rf"^{re.escape(OPENROUTER_API_KEY_ENV)}_(\d+)$")
    numbered: list[tuple[int, str]] = []
    for env_name, env_value in os.environ.items():
        match = numbered_re.match(env_name)
        if not match:
            continue
        normalized = _normalize_api_key_value(env_value)
        if not normalized:
            continue
        numbered.append((int(match.group(1)), normalized))
    numbered.sort(key=lambda item: item[0])
    sources.extend(
        _OpenRouterKeySource(
            name=f"{OPENROUTER_API_KEY_ENV}_{index}",
            values=(value,),
            rotation_source=True,
        )
        for index, value in numbered
    )
    return _apply_account_routing(tuple(sources))


def _apply_account_routing(
    sources: tuple[_OpenRouterKeySource, ...],
) -> tuple[_OpenRouterKeySource, ...]:
    """Constrain the key ring to the account that owns this repository's spend.

    The rule is that the ring never crosses billing accounts -- not that rotation
    stops. Rotating between several keys belonging to the same account is
    legitimate and is preserved; rotating from one account onto another would
    move spend somewhere nobody chose, so a foreign account's credential is
    dropped from the ring instead of being failed over to.
    """

    routed = _routed_account_key()
    if routed is None:
        return sources
    account, routed_key = routed

    foreign_keys = {
        key
        for other, env_name in ACCOUNT_KEY_ENV.items()
        if other != account
        for key in (_normalize_api_key_value(os.environ.get(env_name)),)
        if key
    }

    retained: list[_OpenRouterKeySource] = []
    for source in sources:
        kept = tuple(value for value in source.values if value not in foreign_keys)
        if not kept:
            logger.info(
                "OpenRouter account routing: dropped %s; it belongs to another billing account "
                "and this repository bills %s.",
                source.name,
                account,
            )
            continue
        retained.append(
            _OpenRouterKeySource(name=source.name, values=kept, rotation_source=source.rotation_source)
        )

    if not retained:
        # Nothing configured for this account, or everything present belonged to
        # another one. Use the owning account's own credential.
        if routed_key is None:
            raise LLMConfigurationError(
                f"OpenRouter account {account!r} owns this repository's spend but "
                f"{ACCOUNT_KEY_ENV[account]} is not set, and every other configured key "
                f"belongs to a different billing account. Set {ACCOUNT_KEY_ENV[account]}, "
                f"or set LLM_CLIENT_OPENROUTER_ACCOUNT to bill a different account deliberately."
            )
        return (
            _OpenRouterKeySource(
                name=f"{ACCOUNT_KEY_ENV[account]} (account={account})",
                values=(routed_key,),
                rotation_source=False,
            ),
        )

    if routed_key is None or routed_key not in {value for source in retained for value in source.values}:
        # Keys survived that match no configured account. They cannot be proven
        # to belong to the owning account, so say so rather than bill silently.
        logger.warning(
            "OpenRouter account routing: this repository bills %s, but the configured key ring "
            "contains no key matching %s. Verify which account is being charged.",
            account,
            ACCOUNT_KEY_ENV[account],
        )
    return tuple(retained)


def _openrouter_key_candidates_from_env() -> tuple[str, ...]:
    """Collect deduplicated OpenRouter keys from supported sources in stable order."""
    candidates = [
        value
        for source in _openrouter_key_sources_from_env()
        for value in source.values
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for key in candidates:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return tuple(deduped)


# ---------------------------------------------------------------------------
# Key masking and detection
# ---------------------------------------------------------------------------


def _mask_api_key(key: str | None) -> str:
    """Return a safe, short key fingerprint for logs/warnings."""
    normalized = _normalize_api_key_value(key)
    if not normalized:
        return "<empty>"
    return f"...{normalized[-4:]}"


def _is_openrouter_call(model: str, api_base: str | None) -> bool:
    """Best-effort OpenRouter call detection."""
    model_lower = str(model or "").strip().lower()
    if model_lower.startswith("openrouter/"):
        return True
    base_lower = str(api_base or "").strip().lower()
    return "openrouter.ai" in base_lower


def _reject_unsafe_openrouter_model_selection(call_kwargs: Mapping[str, Any]) -> None:
    """Reject payload-level routes that can bypass pre-dispatch model policy."""

    primary_model = str(call_kwargs.get("model", "") or "").strip().lower()
    if primary_model in {"auto", "auto-beta", "openrouter/auto", "openrouter/auto-beta"}:
        raise ValueError(
            "OpenRouter model-selection policy rejects Auto Router; "
            "use an explicit policy-approved model ID"
        )

    if call_kwargs.get("preset") is not None:
        raise ValueError(
            "OpenRouter model-selection policy rejects account-side presets; "
            "use an explicit policy-approved model ID"
        )

    plugins = call_kwargs.get("plugins")
    if isinstance(plugins, (list, tuple)):
        for plugin in plugins:
            if isinstance(plugin, Mapping) and str(plugin.get("id", "")).lower() == "auto-router":
                raise ValueError(
                    "OpenRouter model-selection policy rejects the auto-router plugin; "
                    "use an explicit policy-approved model ID"
                )

    for key in ("models", "fallbacks"):
        candidates = call_kwargs.get(key)
        if candidates is None:
            continue
        if not isinstance(candidates, (list, tuple)):
            raise TypeError(f"{key} must be a sequence")
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate = candidate.get("model")
            model_id = str(candidate or "").strip().lower()
            if not model_id:
                continue
            # Import lazily to keep the utility module acyclic at import time.
            from llm_client.execution.call_contracts import _check_model_deprecation

            _check_model_deprecation(model_id)


def compile_openrouter_route_policy(policy: OpenRouterRoutePolicyV1) -> dict[str, Any]:
    """Compile the stable public policy into OpenRouter's provider payload."""

    provider: dict[str, Any] = {"require_parameters": True}
    if policy.allowed_providers is not None:
        provider["only"] = list(policy.allowed_providers)
    if policy.ignored_providers is not None:
        provider["ignore"] = list(policy.ignored_providers)
    if policy.data_collection is not None:
        provider["data_collection"] = policy.data_collection
    if policy.zero_data_retention is not None:
        provider["zdr"] = policy.zero_data_retention
    if not policy.allow_provider_fallbacks:
        provider["allow_fallbacks"] = False
    if policy.sort is not None:
        provider["sort"] = policy.sort
    return provider


def _apply_openrouter_route_policy(
    model: str,
    call_kwargs: dict[str, Any],
    policy: OpenRouterRoutePolicyV1 | None,
) -> None:
    """Apply a typed route policy or reject ambiguous/raw route controls locally."""

    raw_provider = call_kwargs.get("provider")
    api_base = call_kwargs.get("api_base")
    _validate_openrouter_route_policy_model(
        model,
        str(api_base) if api_base is not None else None,
        policy,
    )
    if policy is None:
        return
    if raw_provider is not None:
        raise LLMConfigurationError(
            "openrouter_route_policy cannot be combined with raw provider kwargs",
            error_code="openrouter_route_policy_conflicts_with_provider_kwargs",
        )
    call_kwargs["provider"] = compile_openrouter_route_policy(policy)


def _validate_openrouter_route_policy_model(
    model: str,
    api_base: str | None,
    policy: OpenRouterRoutePolicyV1 | None,
) -> None:
    """Reject a typed policy on a resolved route outside OpenRouter."""

    if policy is None:
        return
    if not _is_openrouter_call(model, api_base):
        raise LLMConfigurationError(
            "openrouter_route_policy requires every resolved model leg to use OpenRouter",
            error_code="openrouter_route_policy_on_non_openrouter_route",
        )


def _apply_openrouter_response_cache_headers(
    headers: dict[str, Any],
    policy: OpenRouterRoutePolicyV1 | None,
) -> None:
    """Compile explicit typed cache intent or reject ambiguous raw controls."""

    if policy is None:
        return
    cache_header_names = {
        OPENROUTER_RESPONSE_CACHE_HEADER.casefold(),
        OPENROUTER_RESPONSE_CACHE_TTL_HEADER.casefold(),
        OPENROUTER_RESPONSE_CACHE_CLEAR_HEADER.casefold(),
    }
    if any(str(name).casefold() in cache_header_names for name in headers):
        raise LLMConfigurationError(
            "openrouter_route_policy cannot be combined with raw response-cache headers",
            error_code="openrouter_route_policy_conflicts_with_cache_headers",
        )
    if policy.response_cache_mode == "disabled":
        headers[OPENROUTER_RESPONSE_CACHE_HEADER] = "false"
        return
    headers[OPENROUTER_RESPONSE_CACHE_HEADER] = "true"
    if policy.response_cache_mode == "refresh":
        headers[OPENROUTER_RESPONSE_CACHE_CLEAR_HEADER] = "true"
    if policy.response_cache_ttl_seconds is not None:
        headers[OPENROUTER_RESPONSE_CACHE_TTL_HEADER] = str(
            policy.response_cache_ttl_seconds
        )


def _openrouter_response_cache_status(raw_response: Any) -> str | None:
    """Return ``hit``/``miss`` from LiteLLM-preserved OpenRouter headers."""

    hidden = getattr(raw_response, "_hidden_params", None)
    if not isinstance(hidden, Mapping):
        return None
    for container_name in ("headers", "additional_headers"):
        headers = hidden.get(container_name)
        if not isinstance(headers, Mapping):
            continue
        for name, value in headers.items():
            normalized_name = str(name).casefold()
            if normalized_name.startswith("llm_provider-"):
                normalized_name = normalized_name.removeprefix("llm_provider-")
            if normalized_name != "x-openrouter-cache-status":
                continue
            status = str(value).strip().casefold()
            return status if status in {"hit", "miss"} else None
    return None


def _enable_openrouter_inline_metadata(
    model: str,
    call_kwargs: dict[str, Any],
) -> None:
    """Request route evidence and project trace identity without overriding callers.

    OpenRouter can return the selected provider/model and fallback attempts on
    the original completion response.  Requesting that evidence avoids a
    synchronous generation-history lookup on ordinary calls.  A caller may
    still explicitly disable the header for one request.

    OpenRouter Broadcast consumes a separate ``trace`` object. The required
    llm_client ``task`` and ``trace_id`` already live in LiteLLM ``metadata``;
    copy those values into otherwise-unset Broadcast fields so account-side
    destinations can join their traces to local evidence. Explicit caller
    trace hierarchy and custom fields always win.
    """

    policy_value = call_kwargs.pop("openrouter_route_policy", None)
    if isinstance(policy_value, Mapping):
        policy_value = OpenRouterRoutePolicyV1.model_validate(policy_value)
    if policy_value is not None and not isinstance(policy_value, OpenRouterRoutePolicyV1):
        raise TypeError("openrouter_route_policy must be an OpenRouterRoutePolicyV1")
    _apply_openrouter_route_policy(model, call_kwargs, policy_value)

    api_base = call_kwargs.get("api_base")
    if not _is_openrouter_call(
        model,
        str(api_base) if api_base is not None else None,
    ):
        return

    _reject_unsafe_openrouter_model_selection(call_kwargs)

    normalized_present = sorted(
        key for key in _OPENROUTER_NORMALIZED_PASSTHROUGH_PARAMS if key in call_kwargs
    )
    if normalized_present:
        configured_allowed = call_kwargs.get("allowed_openai_params")
        if configured_allowed is None:
            allowed: list[str] = []
        elif isinstance(configured_allowed, (list, tuple, set, frozenset)):
            allowed = [str(value) for value in configured_allowed]
        else:
            raise TypeError("allowed_openai_params must be a sequence")
        call_kwargs["allowed_openai_params"] = sorted(
            set([*allowed, *normalized_present])
        )

        configured_provider = call_kwargs.get("provider")
        if configured_provider is None:
            provider: dict[str, Any] = {}
        elif isinstance(configured_provider, Mapping):
            provider = dict(configured_provider)
        else:
            raise TypeError("provider must be a mapping")
        if provider.get("require_parameters") is False:
            raise ValueError(
                "OpenRouter provider.require_parameters=False would allow a "
                "normalized control to be silently ignored"
            )
        provider["require_parameters"] = True
        call_kwargs["provider"] = provider

    configured = call_kwargs.get("extra_headers")
    if configured is None:
        headers: dict[str, Any] = {}
    elif isinstance(configured, Mapping):
        headers = dict(configured)
    else:
        raise TypeError("extra_headers must be a mapping")
    _apply_openrouter_response_cache_headers(headers, policy_value)
    if not any(
        str(name).lower() == OPENROUTER_METADATA_HEADER.lower()
        for name in headers
    ):
        headers[OPENROUTER_METADATA_HEADER] = "enabled"
    call_kwargs["extra_headers"] = headers

    if (
        policy_value is not None
        and policy_value.response_cache_mode in {"enabled", "refresh"}
    ):
        if call_kwargs.get("trace") is not None:
            raise LLMConfigurationError(
                "OpenRouter response caching cannot be combined with a request-body "
                "Broadcast trace because the trace changes the exact-response cache key",
                error_code="openrouter_response_cache_conflicts_with_trace_body",
            )
        # Local task/trace custody remains in metadata and llm_client's ledger.
        # Do not copy per-call identity into OpenRouter's request body: OpenRouter
        # hashes the full body, so doing so would turn every logical retry into a
        # distinct cache entry.
        return

    metadata = call_kwargs.get("metadata")
    if not isinstance(metadata, Mapping):
        return
    task = metadata.get("task")
    trace_id = metadata.get("trace_id")
    if not isinstance(task, str) and not isinstance(trace_id, str):
        return

    configured_trace = call_kwargs.get("trace")
    if configured_trace is None:
        trace: dict[str, Any] = {}
    elif isinstance(configured_trace, Mapping):
        trace = dict(configured_trace)
    else:
        raise TypeError("trace must be a mapping")
    if isinstance(trace_id, str) and trace_id.strip():
        trace.setdefault("trace_id", trace_id)
    if isinstance(task, str) and task.strip():
        trace.setdefault("trace_name", task)
        trace.setdefault("generation_name", task)
    if trace:
        call_kwargs["trace"] = trace


# ---------------------------------------------------------------------------
# Key limit error detection
# ---------------------------------------------------------------------------


def _is_openrouter_key_limit_error(error: Exception) -> bool:
    """Whether an error is OpenRouter key/quota exhaustion suitable for key rotation."""
    text = str(error or "").lower()
    status = _error_status_code(error)

    key_limit = ("key limit exceeded" in text) or ("key limit reached" in text)
    insufficient_credits = (
        ("insufficient credits" in text)
        or ("insufficient quota" in text)
        or (status == 402)
    )
    if not (key_limit or insufficient_credits):
        return False

    if status not in {None, 402, 403}:
        return False

    provider = str(getattr(error, "llm_provider", "") or "").lower()
    model = str(getattr(error, "model", "") or "").lower()
    if "openrouter" in provider or model.startswith("openrouter/") or "openrouter" in text:
        return True
    if key_limit:
        return status in {None, 403}
    return status == 402


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


def _reset_openrouter_key_rotation_state() -> None:
    """Test helper: reset OpenRouter key-ring cache/index."""
    global _OPENROUTER_KEY_RING, _OPENROUTER_KEY_RING_INDEX  # noqa: PLW0603
    with _OPENROUTER_KEY_ROTATION_LOCK:
        _OPENROUTER_KEY_RING = ()
        _OPENROUTER_KEY_RING_INDEX = 0


def _rotate_openrouter_api_key() -> tuple[str, str, int] | None:
    """Rotate OPENROUTER_API_KEY to the next configured key, if available."""
    global _OPENROUTER_KEY_RING, _OPENROUTER_KEY_RING_INDEX  # noqa: PLW0603

    with _OPENROUTER_KEY_ROTATION_LOCK:
        ring = _openrouter_key_candidates_from_env()
        if not ring:
            return None

        if ring != _OPENROUTER_KEY_RING:
            _OPENROUTER_KEY_RING = ring
            current_env_key = _normalize_api_key_value(os.environ.get(OPENROUTER_API_KEY_ENV))
            if current_env_key and current_env_key in ring:
                _OPENROUTER_KEY_RING_INDEX = ring.index(current_env_key)
            elif _OPENROUTER_KEY_RING_INDEX >= len(ring):
                _OPENROUTER_KEY_RING_INDEX = 0

        if len(ring) < 2:
            return None

        current_env_key = _normalize_api_key_value(os.environ.get(OPENROUTER_API_KEY_ENV))
        if current_env_key and current_env_key in ring:
            current_idx = ring.index(current_env_key)
        else:
            current_idx = _OPENROUTER_KEY_RING_INDEX

        next_idx = (current_idx + 1) % len(ring)
        if next_idx == current_idx:
            return None

        old_key = ring[current_idx]
        new_key = ring[next_idx]
        os.environ[OPENROUTER_API_KEY_ENV] = new_key
        _OPENROUTER_KEY_RING_INDEX = next_idx
        return old_key, new_key, len(ring)


# ---------------------------------------------------------------------------
# Retry with key rotation
# ---------------------------------------------------------------------------


def _maybe_retry_with_openrouter_key_rotation(
    *,
    error: Exception,
    attempt: int,
    max_retries: int,
    current_model: str,
    current_api_base: str | None,
    user_kwargs: dict[str, Any],
    warning_sink: list[str] | None,
    on_retry: Callable[[int, Exception, float], None] | None,
    caller: str,
) -> bool:
    """Rotate OpenRouter key on key/quota exhaustion and trigger immediate retry."""
    explicit_api_key = bool(_normalize_api_key_value(user_kwargs.get("api_key")))
    if explicit_api_key:
        return False
    if not _is_openrouter_call(current_model, current_api_base):
        return False
    if not _is_openrouter_key_limit_error(error):
        return False

    rotated = _rotate_openrouter_api_key()
    if rotated is None:
        msg = (
            "OPENROUTER_KEY_ROTATION_UNAVAILABLE: received OpenRouter key/quota "
            "exhaustion but no backup keys are configured."
        )
        if warning_sink is not None:
            warning_sink.append(msg)
        logger.warning("%s %s", caller, msg)
        return False

    old_key, new_key, pool_size = rotated
    rotation_msg = (
        "OPENROUTER_KEY_ROTATED: "
        f"{_mask_api_key(old_key)} -> {_mask_api_key(new_key)} "
        f"(pool={pool_size})"
    )
    if warning_sink is not None:
        warning_sink.append(rotation_msg)
    logger.warning("%s %s", caller, rotation_msg)

    if attempt >= max_retries:
        return False

    retry_delay_source = "openrouter_key_rotation"
    delay = 0.0
    if on_retry is not None:
        on_retry(attempt, error, delay)
    if warning_sink is not None:
        warning_sink.append(
            f"RETRY {attempt + 1}/{max_retries + 1}: "
            f"{current_model} ({type(error).__name__}: {error}) "
            f"[retry_delay_source={retry_delay_source}]"
        )
    logger.warning(
        "%s attempt %d/%d failed (retrying immediately, source=%s): %s",
        caller,
        attempt + 1,
        max_retries + 1,
        retry_delay_source,
        error,
    )
    return True


# ---------------------------------------------------------------------------
# Routing enablement
# ---------------------------------------------------------------------------


def _openrouter_routing_enabled() -> bool:
    """Whether automatic OpenRouter model normalization is enabled."""
    raw = os.environ.get(OPENROUTER_ROUTING_ENV, "on").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on", ""}:
        return True
    logger.warning(
        "Invalid %s=%r; expected on/off boolean. Defaulting to on.",
        OPENROUTER_ROUTING_ENV,
        raw,
    )
    return True
