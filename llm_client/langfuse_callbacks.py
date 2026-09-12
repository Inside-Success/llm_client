"""Langfuse observability integration via LiteLLM's built-in callback mechanism.

Activates Langfuse as a complementary observability backend alongside the default
JSONL+SQLite logging. Langfuse is never required -- it activates only when both
conditions are met:

    1. ``LITELLM_CALLBACKS`` includes ``langfuse_otel`` or legacy ``langfuse``
    2. The ``langfuse`` package is importable

External callbacks are metadata-only by default. Set
``LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT=full`` only when the caller has
explicitly authorized prompt and response export.

LiteLLM reads Langfuse credentials from standard env vars automatically:
    ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, ``LANGFUSE_HOST``

Usage (shell)::

    export LITELLM_CALLBACKS=langfuse_otel
    export LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT=metadata_only
    export LANGFUSE_PUBLIC_KEY=pk-lf-...
    export LANGFUSE_SECRET_KEY=sk-lf-...
    export LANGFUSE_HOST=https://cloud.langfuse.com   # or self-hosted

Once configured, every ``litellm.completion()`` / ``litellm.acompletion()`` call
is automatically traced in Langfuse. The ``task=`` and ``trace_id=`` metadata
from llm_client calls flows through as Langfuse trace metadata via litellm's
``metadata`` kwarg.

Install the optional dependency::

    pip install llm-client[langfuse]
"""

from __future__ import annotations

import logging
import os
from typing import Literal, cast

from pydantic import Field

try:
    from data_contracts import BoundaryModel, boundary
except ImportError:

    def boundary(*args, **kwargs):  # type: ignore[misc]
        def decorator(fn):  # type: ignore[misc]
            return fn

        return decorator

    from pydantic import BaseModel as BoundaryModel  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CALLBACK_NAMES = ("langfuse_otel", "langfuse")
_CONTENT_POLICY_ENV = "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT"
ExternalContentPolicy = Literal["metadata_only", "full"]


class LangfuseCallbackConfig(BoundaryModel):
    """Configuration state describing whether Langfuse callbacks are active."""

    model_config = {"extra": "forbid"}

    enabled: bool = Field(
        description="Whether Langfuse env vars are present and callbacks were activated"
    )
    host: str | None = Field(
        description="Configured Langfuse callback endpoint, if set"
    )
    callback: str | None = Field(
        description="The registered LiteLLM Langfuse callback name, if active"
    )
    content_policy: ExternalContentPolicy | None = Field(
        description="External prompt/response export policy, if Langfuse is active"
    )


_initialized: bool = False
_configured_callback: str | None = None
_configured_content_policy: ExternalContentPolicy | None = None


def _configured_host(callback: str | None) -> str | None:
    """Resolve the endpoint variable used by the selected integration."""
    if callback == "langfuse_otel":
        return os.environ.get("LANGFUSE_OTEL_HOST") or os.environ.get("LANGFUSE_HOST")
    return os.environ.get("LANGFUSE_HOST")


def _external_content_policy() -> ExternalContentPolicy:
    """Return the explicit external-content policy, defaulting to metadata-only."""
    raw = os.environ.get(_CONTENT_POLICY_ENV, "metadata_only").strip().lower()
    if raw not in {"metadata_only", "full"}:
        raise ValueError(
            f"{_CONTENT_POLICY_ENV} must be 'metadata_only' or 'full', got {raw!r}"
        )
    return cast(ExternalContentPolicy, raw)


@boundary(
    name="llm_client.langfuse_callback_config",
    producer="llm_client",
    consumers=["observability"],
)
def configure_langfuse_callbacks() -> LangfuseCallbackConfig:
    """Register Langfuse in LiteLLM's callback lists if env-configured.

    Reads ``LITELLM_CALLBACKS`` for a comma-separated list of callback names.
    If a supported Langfuse callback name is present, verifies the package is
    importable, applies the external-content policy, then registers that name
    with LiteLLM's success and failure callback lists.

    Returns LangfuseCallbackConfig describing activation state.
    Idempotent -- safe to call multiple times.
    """
    global _configured_callback, _configured_content_policy, _initialized

    if _initialized:
        active = _is_active()
        return LangfuseCallbackConfig(
            enabled=active,
            host=_configured_host(_configured_callback) if active else None,
            callback=_configured_callback if active else None,
            content_policy=_configured_content_policy if active else None,
        )

    callbacks_env = os.environ.get("LITELLM_CALLBACKS", "")
    requested = [cb.strip().lower() for cb in callbacks_env.split(",") if cb.strip()]

    callback = next((name for name in _CALLBACK_NAMES if name in requested), None)
    if callback is None:
        _initialized = True
        return LangfuseCallbackConfig(
            enabled=False, host=None, callback=None, content_policy=None
        )

    content_policy = _external_content_policy()

    try:
        import langfuse  # noqa: F401
    except ImportError:
        logger.warning(
            "LITELLM_CALLBACKS includes 'langfuse' but the langfuse package is not "
            "installed. Install it with: pip install llm-client[langfuse]"
        )
        _initialized = True
        return LangfuseCallbackConfig(
            enabled=False, host=None, callback=None, content_policy=None
        )

    import litellm

    if content_policy == "metadata_only":
        # LiteLLM owns callback payload construction. This supported global
        # switch removes request messages and generated content while retaining
        # metadata, timing, model, usage, and cost fields for external callbacks.
        litellm.turn_off_message_logging = True

    if callback not in litellm.success_callback:
        litellm.success_callback.append(callback)  # type: ignore[attr-defined]
    if callback not in litellm.failure_callback:
        litellm.failure_callback.append(callback)  # type: ignore[attr-defined]

    _configured_callback = callback
    _configured_content_policy = content_policy
    _initialized = True
    logger.info(
        "Langfuse callback %s activated with external content policy %s",
        callback,
        content_policy,
    )
    return LangfuseCallbackConfig(
        enabled=True,
        host=_configured_host(callback),
        callback=callback,
        content_policy=content_policy,
    )


def _is_active() -> bool:
    """Check whether Langfuse callbacks are currently registered in LiteLLM."""
    try:
        import litellm

        return any(callback in litellm.success_callback for callback in _CALLBACK_NAMES)
    except ImportError:
        return False


def inject_metadata(
    kwargs: dict[str, object],
    *,
    task: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Inject task/trace_id into litellm's metadata kwarg for callback propagation.

    Merges llm_client's ``task`` and ``trace_id`` into the ``metadata`` dict that
    litellm passes to all registered callbacks (including Langfuse). Preserves any
    existing metadata the caller already set.

    This is a no-op when both task and trace_id are None.
    """
    meta: dict[str, object] = {"_llm_client_logged": True}
    if task is not None:
        meta["task"] = task
    if trace_id is not None:
        meta["trace_id"] = trace_id

    existing = kwargs.get("metadata")
    if isinstance(existing, dict):
        existing.update(meta)
    else:
        kwargs["metadata"] = meta
